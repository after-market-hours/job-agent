"""Generic careers-page scanner for companies that don't use Ashby/Greenhouse/Lever.

Two passes, cheapest first:
  1. static: plain HTTP fetch of `careers_url`, keep links whose text looks like a target role.
  2. deep: only if `deep` is on (weekly) and the static pass found no links at all, render the page in
     headless Chromium (needed for JavaScript-built career pages).
Posting dates aren't available, so `posted_at` is the first time the role was seen (the tracker dedupes,
so a role is only reported once).
"""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from ..enrich import strip_html
from ..models import Job
from ..util import parse_dt

H ={"User-Agent": "Mozilla/5.0 (job-agent personal use)"}
A_TAG = re.compile(r'<a\b[^>]*?href="([^"#]+)"[^>]*>(.*?)</a>', re.S | re.I)
DEEP = False  # set by the pipeline (weekly)


NOT_A_JOB_TITLE = re.compile(
    r"playbook|blog|webinar|case stud|e-?book|guide|template|report|podcast|resources?|learn|how to|teams? win|customers?|"
    r"pricing|demo|solutions?|platform|newsletter|press|news|events?|academy|community|partners?|integrations?|compare|vs\.?\b",
    re.I)
JOB_MARKERS = re.compile(
    r"responsibilit|requirements?|qualifications?|what you.ll (?:do|bring)|about the role|about you|who you are|you will|"
    r"you.ll|apply (?:now|for|here)|years of experience|compensation|benefits", re.I)


def looks_like_job(title: str, body: str) -> bool:
    """Reject marketing/nav links that merely contain a keyword (e.g. 'Playbooks: how 5000+ GTM teams win')."""
    if len(title) > 90 or len(title.split()) > 14 or NOT_A_JOB_TITLE.search(title):
        return False
    return len({m.group(0).lower() for m in JOB_MARKERS.finditer(body)}) >= 3 and len(body) > 600


def _guess_location(body: str) -> str:
    """Careers pages rarely have structured locations; use the earliest known city mentioned."""
    low = body.lower()
    hits = [(low.find(c.lower()), c) for c in ("San Francisco", "New York", "NYC", "Brooklyn", "Los Angeles", "Austin",
                                                "Boston", "Chicago", "Seattle", "Remote") if c.lower() in low]
    return min(hits)[1] if hits else ""


def _job(company: dict, href: str, title: str, body: str) -> Job:
    return Job(
        ats="web", slug=company["slug"], ext_id=hashlib.sha1(href.encode()).hexdigest()[:12],
        company=company["name"], stage=company.get("stage", ""), title=title, url=href, apply_url=href,
        location=_guess_location(body), posted_at=datetime.now(timezone.utc), description=body,
    )


def _static(company: dict, cfg: dict) -> tuple[list[Job], int]:
    from ..rank import title_ok

    url = company["careers_url"]
    page = requests.get(url, headers=H, timeout=15).text
    links, seen = [], set()
    for href, inner in A_TAG.findall(page):
        chunks = [html.unescape(c).strip() for c in re.split(r"<[^>]+>", inner) if c.strip()]
        title = re.sub(r"\s+", " ", chunks[0]).strip()[:120] if chunks else ""  # first text node = the role name
        full = urljoin(url, href)
        if title and full not in seen and title_ok(title, cfg):
            seen.add(full)
            links.append((full, title))
    jobs = []
    for full, title in links:
        try:
            raw = requests.get(full, headers=H, timeout=15).text
        except requests.RequestException:
            raw = ""
        body = strip_html(raw)
        if looks_like_job(title, body):
            job = _job(company, full, title, body)
            m = re.search(r'"datePosted"\s*:\s*"([^"]+)"', raw)  # schema.org JobPosting, when the page has it
            if m and parse_dt(m.group(1)):
                job.posted_at = parse_dt(m.group(1))
            jobs.append(job)
    return jobs, len(re.findall(r"<a\b", page))


def _deep(company: dict, cfg: dict) -> list[Job]:
    from playwright.sync_api import sync_playwright

    from ..rank import title_ok

    url = company["careers_url"]
    out = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=25000)
        pg.wait_for_timeout(2500)
        anchors = pg.evaluate("() => [...document.querySelectorAll('a')].map(a => ({t: (a.innerText||'').trim().split('\\n')[0], h: a.href}))")
        seen = set()
        for a in anchors:
            title = a["t"][:120]
            if not title or a["h"] in seen or not title_ok(title, cfg):
                continue
            seen.add(a["h"])
            try:
                pg.goto(a["h"], wait_until="domcontentloaded", timeout=25000)
                pg.wait_for_timeout(1000)
                body = pg.inner_text("body")
            except Exception:
                body = ""
            if looks_like_job(title, body):
                out.append(_job(company, a["h"], title, body))
        b.close()
    return out


def fetch(company: dict) -> list[Job]:
    from ..pipeline import load_yaml

    cfg = load_yaml("filters.yaml")
    jobs, n_links = _static(company, cfg)
    if jobs or not DEEP or n_links > 40:  # plenty of static links but no target role => nothing to find
        return jobs
    return _deep(company, cfg)


def custom_questions(job: Job):
    return None  # arbitrary site: checked at apply time
