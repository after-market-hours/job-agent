"""a16z speedrun talent network aggregator.

Searches the board for each target role keyword, then reads each job page's schema.org JobPosting
data (description, date, salary, location) and its real apply link. When the apply link is a
supported ATS (Ashby/Greenhouse/Lever) the job gets that ATS identity so it dedupes with direct scans.
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

BASE = "https://speedrun-talent-network.com"
H = {"User-Agent": "Mozilla/5.0 (job-agent personal use)"}
QUERIES = ["chief of staff", "strategy operations", "business operations", "bizops", "gtm", "go to market",
           "revenue operations", "sales operations", "growth operations", "marketing operations"]
ATS_LINK = [
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([^/\"?#]+)/([0-9a-f\-]{36})")),
    ("greenhouse", re.compile(r"(?:job-boards|boards)\.greenhouse\.io/([^/\"?#]+)/jobs/(\d+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([^/\"?#]+)/([0-9a-f\-]{36})")),
]


def _jobposting(page: str) -> dict | None:
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            d = json.loads(m)
        except ValueError:
            continue
        for x in (d.get("@graph") if isinstance(d, dict) and "@graph" in d else [d]):
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                return x
    return None


def _one(path: str) -> Job | None:
    try:
        page = requests.get(BASE + path, headers=H, timeout=30).text
    except requests.RequestException:
        return None
    jp = _jobposting(page)
    if not jp:
        return None
    org = (jp.get("hiringOrganization") or {}).get("name", "")
    addr = ((jp.get("jobLocation") or {}).get("address") or {}) if isinstance(jp.get("jobLocation"), dict) else {}
    loc = ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressRegion")) if x)
    if jp.get("jobLocationType") == "TELECOMMUTE":
        loc = (loc + " (Remote)").strip()
    sal = (jp.get("baseSalary") or {}).get("value") or {}
    comp = ""
    if sal.get("minValue") and sal.get("maxValue"):
        comp = f"${sal['minValue']:,.0f} – ${sal['maxValue']:,.0f}"
    apply = next((u for u in re.findall(r'href="(https?://[^"]+)"', page)
                  if re.search(r"ashbyhq|greenhouse|lever\.co|workable|rippling|gem\.com|dover|teamtailor", u)), "")
    ats, slug, ext = "web", "speedrun", path.rsplit("-", 1)[-1]
    for name, rx in ATS_LINK:
        m = rx.search(apply)
        if m:
            ats, slug, ext = name, m.group(1), m.group(2)
            break
    return Job(
        ats=ats, slug=slug, ext_id=ext, company=html.unescape(org), stage="", title=html.unescape(jp.get("title", "")),
        url=BASE + path, apply_url=apply or BASE + path, location=loc,
        posted_at=parse_dt(jp.get("datePosted")), description=strip_html(jp.get("description", "")), structured_comp=comp,
    )


def fetch_all() -> list[Job]:
    from ..pipeline import load_yaml
    from ..rank import title_ok

    cfg = load_yaml("filters.yaml")

    def search(q):
        try:
            r = requests.get(f"{BASE}/jobs", params={"q": q}, headers=H, timeout=30)
            return set(re.findall(r'href="(/jobs/[a-z0-9\-]+-[0-9a-f]{8})"', r.text))
        except requests.RequestException:
            return set()

    with cf.ThreadPoolExecutor(5) as ex:
        links = set().union(*ex.map(search, QUERIES))
    # the URL slug starts with the job title; cheap pre-filter before fetching each page
    links = {l for l in links if title_ok(l.split("/jobs/")[1].rsplit("-", 1)[0].replace("-", " "), cfg)}
    with cf.ThreadPoolExecutor(8) as ex:
        return [j for j in ex.map(_one, sorted(links)) if j]
