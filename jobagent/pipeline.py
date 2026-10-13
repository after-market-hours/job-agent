from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
from pathlib import Path

import yaml

from . import db
from .enrich import enrich
from .models import Job
from .rank import age_days, location_ok, sort_key, title_ok
from .sources import FETCHERS, FORM_CHECKERS, getro, speedrun
from .vet import Vetter

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("jobagent")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8")) or {}


def run(con, limit: int | None = None, persist: bool = True) -> tuple[list[Job], dict]:
    cfg = load_yaml("filters.yaml")
    comp_cfg = load_yaml("companies.yaml")
    allowed = set(comp_cfg.get("allowed_stages", []))
    companies = [c for c in comp_cfg["companies"] if c.get("stage") in allowed]
    disc = ROOT / "data" / "discovered.json"
    have = {(c["ats"], c["slug"]) for c in companies}
    if disc.exists():  # YC / harvested early-stage companies (see `cli.py harvest`)
        for c in json.loads(disc.read_text(encoding="utf-8")):
            if (c["ats"], c["slug"]) not in have and c.get("early"):
                companies.append(c)
                have.add((c["ats"], c["slug"]))
    limit = limit or cfg.get("daily_limit", 20)
    stats = {"companies": len(companies), "fetched": 0, "title_match": 0, "too_old": 0, "no_sponsorship": 0,
             "exp_6plus": 0, "dup": 0, "source_errors": 0}

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
    from datetime import date
    from .sources import web
    web.DEEP = date.today().weekday() == 0 or bool(os.environ.get("JOBAGENT_DEEP"))  # browser pass: Mondays only
    with cf.ThreadPoolExecutor(4) as ex:  # browser scans are heavier
        all_jobs += [j for batch in ex.map(fetch, web_cos) for j in batch]
    try:  # accelerator aggregator (a16z speedrun talent network)
        all_jobs += speedrun.fetch_all()
    except Exception as e:
        log.warning("speedrun source failed: %s", e)
        stats["source_errors"] += 1
    try:  # VC portfolio boards (Getro): consumer/DTC and general startups with funding stage attached
        all_jobs += getro.fetch_all()
    except Exception as e:
        log.warning("getro source failed: %s", e)
        stats["source_errors"] += 1
    stats["fetched"] = len(all_jobs)
    vetter = Vetter()

    known = db.known_ids(con)
    cands: list[Job] = []
    unvetted: set[str] = set()
    for j in all_jobs:
        if not title_ok(j.title, cfg):
            continue
        if not location_ok(f"{j.location} {j.title}", cfg):
            continue
        verdict, stage = vetter.verdict(j.company)
        if verdict in ("late", "public"):
            stats["not_early_stage"] = stats.get("not_early_stage", 0) + 1
            continue
        if verdict == "unverified":
            # the source itself may carry a funding stage (VC boards): trust it, otherwise hold the company back
            if j.stage in ("seed", "A", "B"):
                stage = j.stage
            else:
                unvetted.add(j.company)
                continue
        j.stage = stage
        stats["title_match"] += 1
        if age_days(j) > cfg.get("max_age_days", 30):
            stats["too_old"] += 1
            continue
        if j.id in known:
            stats["dup"] += 1
            continue
        enrich(j, cfg.get("max_lone_min_years", 5))
        if j.visa_flag == "excluded":
            # dropped entirely: not stored, so it is simply re-evaluated (and re-dropped) each run
            stats["no_sponsorship"] += 1
            continue
        if j.exp_excluded:
            stats["exp_6plus"] += 1
            if persist:
                db.mark_seen(con, j.id, "exp_6plus")
            continue
        cands.append(j)
    uniq = {}
    for j in cands:
        uniq.setdefault(j.id, j)
    cands = list(uniq.values())
    cands.sort(key=sort_key)
    picked = cands[:limit]

    def check(j: Job):
        try:
            j.custom_questions = FORM_CHECKERS[j.ats](j)
        except Exception as e:
            log.info("form check failed for %s: %s", j.id, e)
            j.custom_questions = None

    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(check, picked))
    stats["unvetted"] = sorted(unvetted)
    con.commit()
    return picked, stats
