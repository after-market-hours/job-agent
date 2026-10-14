"""a16z portfolio job board (jobs.a16z.com): server-rendered cards with company, role, location, posted date,
funding stage, headcount, salary (when listed) and the real apply link (Greenhouse / Ashby / Lever / company site)."""
from __future__ import annotations

import concurrent.futures as cf
import html
import re

import requests

from ..models import Job
from ..util import parse_dt
from .describe import describe
from .speedrun import ATS_LINK

BASE = "https://jobs.a16z.com"
QUERIES = ["chief of staff", "strategy", "strategic", "operations", "business operations", "bizops", "gtm", "go to market",
           "revenue operations", "sales operations", "growth", "marketing operations", "founder's office", "special projects",
           "finance and strategy"]  # the board returns 25 cards per query and has no server-side paging, so use many queries
STAGE_RX = re.compile(r"^(Pre-?seed|Seed|Series [A-Z]|Growth|IPO|Public|Acquired|Late stage)$", re.I)
STAGE = {"seed": "seed", "pre-seed": "seed", "preseed": "seed", "series a": "A", "series b": "B", "series c": "C"}
UA = {"User-Agent": "Mozilla/5.0"}


def _texts(fragment: str) -> list[str]:
    parts = [html.unescape(t).strip() for t in re.split(r"<[^>]+>", fragment)]
    return [p for p in parts if p and p != "·"]


def parse(page: str) -> list[dict]:
    page = re.sub(r"<svg.*?</svg>", "", page, flags=re.S)
    page = re.sub(r'\s(?:class|style)="[^"]*"', "", page)
    out = []
    for art in re.findall(r"<article\b.*?</article>", page, re.S):
        m = re.search(r'<h2[^>]*><a href="([^"]+)">(.*?)</a></h2>(.*?)</article>', art, re.S)
        co = re.search(r'<a href="/(?:jobs|company)/[^"]*">([^<]+)</a>', art)
        if not (m and co):
            continue
        path, title, rest = m.group(1), html.unescape(m.group(2)), m.group(3)
        apply = re.search(r'<a href="(https?://[^"]+)"[^>]*target="_blank"', rest)
        when = re.search(r'<time dateTime="([^"]+)"', rest)
        loc = sal = stage = ""
        for t in _texts(rest):
            if t in ("Apply", "Interested") or t.startswith("Posted"):
                continue
            if STAGE_RX.match(t):
                stage = t
            elif "employees" in t:
                continue
            elif re.search(r"USD|\$\s?\d|€|£", t):
                sal = t
            elif not loc and len(t) < 90:
                loc = t
        out.append({"company": html.unescape(co.group(1)), "title": title, "path": path, "apply": apply.group(1) if apply else "",
                    "posted": when.group(1) if when else None, "location": loc, "salary": sal, "stage": stage})
    return out


def _search(q: str) -> list[dict]:
    try:
        return parse(requests.get(f"{BASE}/jobs", params={"q": q}, headers=UA, timeout=30).text)
    except requests.RequestException:
        return []


def fetch_all() -> list[Job]:
    from ..pipeline import load_yaml
    from ..rank import location_ok, title_ok

    cfg = load_yaml("filters.yaml")
    with cf.ThreadPoolExecutor(5) as ex:
        rows = [r for res in ex.map(_search, QUERIES) for r in res]
    uniq: dict = {}
    for r in rows:
        uniq.setdefault((r["company"], r["title"], r["location"]), r)
    keep = []
    for r in uniq.values():
        stage = STAGE.get(r["stage"].lower(), "")
        if r["stage"] and not stage:
            continue  # growth / series D+ / public
        if not title_ok(r["title"], cfg) or not location_ok(f"{r['location']} {r['title']}", cfg):
            continue
        keep.append((r, stage))

    def build(item):
        r, stage = item
        apply = r["apply"] or BASE + r["path"]
        ats, slug, ext = "web", "a16z", re.sub(r"\W+", "", r["path"])[-24:]
        for name, rx in ATS_LINK:
            m = rx.search(apply)
            if m:
                ats, slug, ext = name, m.group(1), m.group(2)
                break
        comp = r["salary"]  # e.g. "$200K – $300K • Offers Equity" -- enrich() splits salary and equity
        return Job(ats=ats, slug=slug, ext_id=ext, company=r["company"], stage=stage, title=r["title"], url=apply,
                   apply_url=apply, location=r["location"], posted_at=parse_dt(r["posted"]),
                   description=describe(apply), structured_comp=comp)

    with cf.ThreadPoolExecutor(8) as ex:
        return list(ex.map(build, keep))
