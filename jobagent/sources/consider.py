"""VC portfolio job boards on the Consider platform (Forerunner, Sequoia, Kleiner Perkins, First Round, CRV, BVP, Felicis,
Initialized, ...). Each job carries the company's funding stage ('fundingLV') and headcount bucket, an apply link and salary.
Descriptions are read from the apply link (ATS API or page JSON-LD).
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import re

import requests

from ..models import Job
from ..util import parse_dt
from .describe import describe
from .speedrun import ATS_LINK

HOSTS = ["jobs.forerunnerventures.com", "jobs.sequoiacap.com", "jobs.kleinerperkins.com", "jobs.firstround.com",
         "jobs.crv.com", "jobs.bvp.com", "jobs.felicis.com", "jobs.initialized.com"]
QUERIES = ["chief of staff", "strategy operations", "business operations", "gtm", "revenue operations", "growth operations"]
FUNDING = {"seed": "seed", "pre-seed": "seed", "series a": "A", "series b": "B", "series c": "C"}
UA = "Mozilla/5.0 (job-agent personal use)"


def _search_board(host: str) -> list[dict]:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    try:
        page = s.get(f"https://{host}", timeout=25).text
        tok = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', page).group(1)
        bid = re.search(r'"board":\{"id":"([^"]+)"', page).group(1)
    except (requests.RequestException, AttributeError):
        return []
    hdr = {"X-CSRF-Token": tok, "Content-Type": "application/json", "Accept": "application/json"}
    out = []
    for q in QUERIES:
        seq = None
        for _ in range(2):  # 2 pages x 100 per query; results are relevance-ranked, we filter by title client-side
            meta = {"size": 100, **({"sequence": seq} if seq else {})}
            try:
                r = s.post(f"https://{host}/api-boards/search-jobs", headers=hdr, timeout=30,
                           json={"meta": meta, "board": {"id": bid, "isParent": True}, "query": {"promoted": False, "title": q}})
                data = r.json()
            except (requests.RequestException, ValueError):
                break
            for j in data.get("jobs", []):
                j["_host"] = host
                out.append(j)
            seq = (data.get("meta") or {}).get("sequence")
            if not seq or len(data.get("jobs", [])) < 100:
                break
    return out


def fetch_all() -> list[Job]:
    from ..pipeline import load_yaml
    from ..rank import location_ok, title_ok

    cfg = load_yaml("filters.yaml")
    with cf.ThreadPoolExecutor(len(HOSTS)) as ex:
        hits = [j for res in ex.map(_search_board, HOSTS) for j in res]
    uniq: dict = {}
    for j in hits:
        uniq.setdefault((j.get("companyName"), j.get("title")), j)
    keep = []
    for j in uniq.values():
        funding = ((j.get("fundingLV") or {}).get("label") or "").lower()
        stage = FUNDING.get(funding, "")
        if funding and not stage:
            continue  # 'Growth' etc. = later stage
        if (j.get("companyStaffCount") or 0) > 1500 or not title_ok(j["title"], cfg):
            continue
        if not location_ok(" ".join(j.get("locations") or []) + " " + j["title"], cfg):
            continue
        keep.append((j, stage))

    def build(item):
        j, stage = item
        apply = j.get("applyUrl") or j.get("url") or ""
        ats, slug, ext = "web", "consider", str(j.get("jobId"))
        for name, rx in ATS_LINK:
            m = rx.search(apply)
            if m:
                ats, slug, ext = name, m.group(1), m.group(2)
                break
        sal = j.get("salary") or {}
        comp = f"${sal['minValue']:,.0f} – ${sal['maxValue']:,.0f}" if sal.get("minValue") and sal.get("maxValue") else ""
        locs = "; ".join((j.get("locations") or [])[:2]) + (" (Remote)" if j.get("remote") else "")
        return Job(ats=ats, slug=slug, ext_id=ext, company=html.unescape(j.get("companyName", "")), stage=stage,
                   title=html.unescape(j["title"]).strip(), url=apply, apply_url=apply, location=locs,
                   posted_at=parse_dt(j.get("timeStamp")), description=describe(apply), structured_comp=comp)

    with cf.ThreadPoolExecutor(8) as ex:
        return list(ex.map(build, keep))
