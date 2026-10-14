from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
from datetime import date
from pathlib import Path

import yaml

from . import db
from .enrich import enrich
from .models import Job
from .rank import age_days, location_ok, sort_key, title_ok
from .sources import FETCHERS, FORM_CHECKERS, a16z, consider, getro, speedrun, web
from .vet import EARLY, Vetter

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("jobagent")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8")) or {}


def _load_json(name: str) -> list:
    p = ROOT / "data" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def gather_companies(stats: dict) -> list[dict]:
    comp_cfg = load_yaml("companies.yaml")
    allowed = set(comp_cfg.get("allowed_stages", []))
    companies = [c for c in comp_cfg["companies"] if c.get("stage") in allowed]
    have = {(c["ats"], c["slug"]) for c in companies}
    for fname in ("discovered.json", "watchlist.json"):  # YC companies; consumer/industrial watchlist
        for c in _load_json(fname):
            if (c["ats"], c["slug"]) not in have and c.get("early"):
                companies.append(c)
                have.add((c["ats"], c["slug"]))
    stats["companies"] = len(companies)
    return companies


def run(con, limit: int | None = None, persist: bool = True, public_limit: int | None = None) -> tuple[list[Job], dict]:
    cfg = load_yaml("filters.yaml")
    limit = limit or cfg.get("daily_limit", 30)
    public_limit = cfg.get("public_limit", 10) if public_limit is None else public_limit
    stats = {"fetched": 0, "title_match": 0, "too_old": 0, "no_sponsorship": 0, "exp_6plus": 0, "dup": 0,
             "source_errors": 0, "not_early_stage": 0}
    companies = gather_companies(stats)

    def fetch(c):
        try:
            return FETCHERS[c["ats"]](c)
        except Exception as e:  # one broken company must not kill the run
            log.warning("source failed: %s (%s): %s", c["name"], c["ats"], e)
            stats["source_errors"] += 1
            return []

    api_cos = [c for c in companies if c["ats"] != "web"]
    web_cos = [c for c in companies if c["ats"] == "web"]
    with cf.ThreadPoolExecutor(8) as ex:
        all_jobs = [j for batch in ex.map(fetch, api_cos) for j in batch]
    web.DEEP = date.today().weekday() == 0 or bool(os.environ.get("JOBAGENT_DEEP"))  # browser pass: Mondays only
    with cf.ThreadPoolExecutor(4) as ex:  # browser scans are heavier
        all_jobs += [j for batch in ex.map(fetch, web_cos) for j in batch]
    for name, src in (("speedrun", speedrun.fetch_all), ("getro", getro.fetch_all), ("consider", consider.fetch_all), ("a16z", a16z.fetch_all)):
        try:  # aggregator boards: a16z speedrun, Getro VC boards, Consider VC boards
            all_jobs += src()
        except Exception as e:
            log.warning("%s source failed: %s", name, e)
            stats["source_errors"] += 1

    public_jobs: list[Job] = []
    if public_limit:
        try:
            from . import public
            public_jobs, pstats = public.fetch_jobs()
            stats.update(pstats)
        except Exception as e:
            log.warning("public source failed: %s", e)
            stats["source_errors"] += 1
    stats["fetched"] = len(all_jobs) + len(public_jobs)
    vetter = Vetter()

    known = db.known_ids(con)
    pools: dict[str, list[Job]] = {"private": [], "public": []}
    for j in all_jobs + public_jobs:
        if not title_ok(j.title, cfg) or not location_ok(f"{j.location} {j.title}", cfg):
            continue
        if j.kind == "private":
            verdict, stage = vetter.verdict(j.company)
            if verdict in ("late", "public"):
                stats["not_early_stage"] += 1
                continue
            if verdict == "unverified":
                if j.stage in EARLY:      # the source itself carries a funding stage (VC boards)
                    stage = j.stage
                else:                      # unknown stage: skip quietly (logged for later vetting)
                    log.info("unvetted skipped: %s", j.company)
                    continue
            j.stage = stage
            j.badge = vetter.badge(j.company)
        stats["title_match"] += 1
        if age_days(j) > cfg.get("max_age_days", 30):
            stats["too_old"] += 1
            continue
        if j.id in known:
            stats["dup"] += 1
            continue
        enrich(j, cfg.get("max_lone_min_years", 5))
        if j.visa_flag == "excluded":
            stats["no_sponsorship"] += 1  # dropped entirely; re-evaluated (and re-dropped) each run
            continue
        if j.exp_excluded:
            stats["exp_6plus"] += 1
            if persist:
                db.mark_seen(con, j.id, "exp_6plus")
            continue
        pools[j.kind].append(j)

    picked: list[Job] = []
    for kind, n, per_company in (("private", limit, 3), ("public", public_limit, 2)):
        seen_ids, seen_titles, per_co, chosen = set(), set(), {}, []
        for j in sorted(pools[kind], key=sort_key):
            title_key = (j.company, j.title.lower())  # same role listed for several offices => one row
            if j.id in seen_ids or title_key in seen_titles or per_co.get(j.company, 0) >= per_company:
                continue
            seen_ids.add(j.id)
            seen_titles.add(title_key)
            per_co[j.company] = per_co.get(j.company, 0) + 1
            chosen.append(j)
            if len(chosen) >= n:
                break
        picked += chosen

    def check(j: Job):
        try:
            j.custom_questions = FORM_CHECKERS[j.ats](j)
        except Exception as e:
            log.info("form check failed for %s: %s", j.id, e)
            j.custom_questions = None

    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(check, picked))
    con.commit()
    return picked, stats
