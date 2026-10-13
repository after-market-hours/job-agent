"""Find which ATS (or custom careers page) a company hires through, and harvest early-stage
companies from accelerator portfolios (YC) so they can be scanned for open roles."""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
H = {"User-Agent": "Mozilla/5.0 (job-agent personal use)"}
YC_HIRING = "https://yc-oss.github.io/api/companies/hiring.json"

ATS_PATTERNS = [
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.\-]+)")),
    ("greenhouse", re.compile(r"(?:job-boards|boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_\-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_.\-]+)")),
]
CAREER_PATHS = ["/careers", "/jobs", "/company/careers", "/join"]
BAD_SLUGS = {"embed", "jobs", "api", "static"}


def _get(url: str):
    try:
        r = requests.get(url, headers=H, timeout=7)
        return r if r.ok else None
    except requests.RequestException:
        return None


def ats_from_html(text: str):
    for ats, rx in ATS_PATTERNS:
        for m in rx.finditer(text):
            if m.group(1).lower() not in BAD_SLUGS:
                return ats, m.group(1)
    return None


def has_jobs(ats: str, slug: str) -> bool:
    try:
        if ats == "ashby":
            r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=8)
            return r.ok and bool(r.json().get("jobs"))
        if ats == "greenhouse":
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=8)
            return r.ok and bool(r.json().get("jobs"))
        if ats == "lever":
            r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=8)
            return r.ok and isinstance(r.json(), list) and bool(r.json())
    except (requests.RequestException, ValueError):
        pass
    return False


def resolve(name: str, website: str) -> dict | None:
    """Return {ats, slug} or {ats:'web', slug, careers_url} or None."""
    if not website:
        return None
    base = website if website.startswith("http") else "https://" + website
    host = urlparse(base).netloc.lower().removeprefix("www.")
    pages = [base] + [urljoin(base, p) for p in CAREER_PATHS]
    careers = None
    for u in pages:
        r = _get(u)
        if not r:
            continue
        hit = ats_from_html(r.text)
        if hit and has_jobs(*hit):
            return {"ats": hit[0], "slug": hit[1]}
        if u != base and careers is None and len(r.text) > 3000:
            careers = r.url
    # slug guesses from domain/name
    guesses = {host.split(".")[0], re.sub(r"[^a-z0-9]", "", name.lower())}
    for g in guesses:
        for ats in ("ashby", "greenhouse", "lever"):
            if has_jobs(ats, g):
                return {"ats": ats, "slug": g}
    if careers:
        return {"ats": "web", "slug": host.split(".")[0], "careers_url": careers}
    return None


def harvest_yc(min_batch_year: int = 2019, max_team: int = 200) -> list[dict]:
    """YC companies that are hiring, active (not public), early by batch year and team size."""
    data = requests.get(YC_HIRING, headers=H, timeout=60).json()
    picked = []
    for c in data:
        batch = c.get("batch", "")
        m = re.search(r"(\d{4})", batch)
        year = int(m.group(1)) if m else 0
        if c.get("status") != "Active":
            continue
        if year < min_batch_year or (c.get("team_size") or 0) > max_team:
            continue
        picked.append({"name": c["name"], "website": c.get("website", ""), "stage": f"YC {batch}", "early": True,
                       "team_size": c.get("team_size"), "one_liner": c.get("one_liner", "")})
    return picked


def build_cache(limit: int | None = None) -> list[dict]:
    """Resolve each harvested company's ATS; save to data/discovered.json."""
    cos = harvest_yc()
    if limit:
        cos = cos[:limit]

    def go(c):
        try:
            res = resolve(c["name"], c["website"])
        except Exception:
            res = None
        return {**c, **res} if res else None

    found = []
    with cf.ThreadPoolExecutor(48) as ex:
        for i, x in enumerate(ex.map(go, cos), 1):
            if x:
                found.append(x)
            if i % 100 == 0:
                print(f"  ...{i}/{len(cos)} checked, {len(found)} resolved", flush=True)
    out = ROOT / "data" / "discovered.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(found, indent=1), encoding="utf-8")
    return found
