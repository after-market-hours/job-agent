"""VC portfolio job boards powered by Getro (Lerer Hippeau, Maveron, Primary, Greycroft, FirstMark, ...).

Each board exposes a search API that returns jobs together with the hiring company's funding stage,
salary and posting date, so stage vetting for these companies is largely automatic. Descriptions come from
the job's detail page (schema.org JobPosting). Add boards to BOARDS (find the id in the board page source).
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import json
import re

import requests

from ..enrich import strip_html
from ..models import Job
from ..util import parse_dt
from .speedrun import ATS_LINK

# (host, getro network id). Consumer/DTC-leaning boards first.
BOARDS = [
    ("jobs.lererhippeau.com", 120), ("jobs.maveron.com", 810), ("jobs.primary.vc", 1124), ("jobs.greycroft.com", 616),
    ("jobs.firstmark.com", 45303), ("careers.homebrew.co", 440), ("jobs.eniac.vc", 117), ("jobs.trueventures.com", 646),
    ("jobs.nfx.com", 307), ("jobs.menlovc.com", 767), ("careers.redpoint.com", 189), ("jobs.khoslaventures.com", 257),
    ("jobs.svangel.com", 880), ("jobs.8vc.com", 1005), ("jobs.fifthwall.com", 1636), ("jobs.generalcatalyst.com", 222),
    ("jobs.accel.com", 8672),
]
QUERIES = ["chief of staff", "strategy operations", "business operations", "bizops", "gtm", "go to market",
           "revenue operations", "sales operations", "growth operations", "marketing operations"]
H = {"User-Agent": "Mozilla/5.0 (job-agent personal use)", "Content-Type": "application/json", "Accept": "application/json"}

STAGE = {"pre_seed": "seed", "seed": "seed", "series_a": "A", "series_b": "B",
         "series_c": "C", "series_c_plus": "late", "series_d": "late", "series_e": "late", "series_f": "late",
         "series_g": "late", "series_h": "late", "series_i": "late", "ipo": "late", "acquisition": "late",
         "private_equity": "late"}  # anything else (other / series_unknown / none) => '' => unverified


def _search(board: tuple, query: str) -> list[dict]:
    host, nid = board
    out = []
    for page in range(3):
        try:
            r = requests.post(f"https://api.getro.com/api/v2/collections/{nid}/search/jobs", headers=H, timeout=30,
                              json={"hitsPerPage": 100, "page": page, "query": query, "filters": {}})
            res = r.json()["results"]
        except (requests.RequestException, ValueError, KeyError):
            break
        for j in res["jobs"]:
            j["_host"] = host
            out.append(j)
        if len(res["jobs"]) < 100:
            break
    return out


def _description(host: str, j: dict) -> str:
    u = f"https://{host}/companies/{j['organization']['slug']}/jobs/{j['slug']}"
    try:
        page = requests.get(u, headers={"User-Agent": H["User-Agent"]}, timeout=25).text
    except requests.RequestException:
        return ""
    for m in re.findall(r'application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m)
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                return strip_html(x.get("description", ""))
    return ""


def fetch_all() -> list[Job]:
    from ..pipeline import load_yaml
    from ..rank import age_days, location_ok, title_ok

    cfg = load_yaml("filters.yaml")
    tasks = [(b, q) for b in BOARDS for q in QUERIES]
    with cf.ThreadPoolExecutor(8) as ex:
        hits = [j for res in ex.map(lambda t: _search(*t), tasks) for j in res]
    uniq: dict = {}
    for j in hits:
        uniq.setdefault((j["organization"]["name"], j["title"]), j)  # same job appears on several boards/queries

    keep = []
    for j in uniq.values():
        stage = STAGE.get(j["organization"].get("stage") or "", "")
        if stage == "late" or not title_ok(j["title"], cfg):
            continue
        locs = " ".join(j.get("locations") or j.get("searchable_locations") or [])
        if not location_ok(f"{locs} {j['title']}", cfg):
            continue
        keep.append((j, stage))

    def build(item):
        j, stage = item
        org = j["organization"]
        apply = j.get("url", "")
        ats, slug, ext = "web", "getro", str(j["id"])
        for name, rx in ATS_LINK:
            m = rx.search(apply)
            if m:
                ats, slug, ext = name, m.group(1), m.group(2)
                break
        lo, hi = j.get("compensation_amount_min_cents"), j.get("compensation_amount_max_cents")
        comp = f"${lo / 100:,.0f} – ${hi / 100:,.0f}" if lo and hi else ""
        if comp and j.get("compensation_offers_equity"):
            comp += " • Offers Equity"
        locs = j.get("locations") or j.get("searchable_locations") or []
        loc = "; ".join(locs[:2]) + (" (Remote)" if j.get("work_mode") == "remote" else "")
        return Job(
            ats=ats, slug=slug, ext_id=ext, company=html.unescape(org["name"]), stage=stage,
            title=html.unescape(j["title"]).replace("✨", "").strip(), url=apply,
            apply_url=apply, location=loc, posted_at=parse_dt((j.get("created_at") or 0) * 1000 or None),
            description=_description(j["_host"], j), structured_comp=comp,
        )

    with cf.ThreadPoolExecutor(8) as ex:
        return list(ex.map(build, keep))
