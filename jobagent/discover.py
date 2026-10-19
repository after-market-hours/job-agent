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
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_\-]+)")),
    ("rippling", re.compile(r"ats\.rippling\.com/([A-Za-z0-9_\-]+)")),
    ("gem", re.compile(r"jobs\.gem\.com/([A-Za-z0-9_\-]+)")),
    ("bamboohr", re.compile(r"([a-z0-9\-]+)\.bamboohr\.com")),
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
        if ats == "gem":
            r = requests.get(f"https://api.gem.com/job_board/v0/{slug}/job_posts/", headers=H, timeout=8)
            return r.ok and isinstance(r.json(), list) and bool(r.json())
        if ats == "rippling":
            r = requests.get(f"https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs", headers=H, timeout=8)
            return r.ok and isinstance(r.json(), list) and bool(r.json())
        if ats == "workable":
            r = requests.post(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", headers=H, timeout=8,
                              json={"query": "", "location": [], "department": [], "worktype": [], "remote": []})
            return r.ok and bool(r.json().get("results"))
        if ats == "bamboohr" and slug not in ("www", "app", "help", "documentation"):
            r = requests.get(f"https://{slug}.bamboohr.com/careers/list", headers={**H, "Accept": "application/json"}, timeout=8)
            return r.ok and "json" in r.headers.get("content-type", "") and bool(r.json().get("result"))
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


def _ashby_slug(name: str, domain: str) -> str | None:
    """Ashby board slug for a company: slug guesses from its name / domain first, then an Ashby link on its careers page."""
    host = urlparse(domain if domain.startswith("http") else "https://" + domain).netloc.lower().removeprefix("www.") if domain else ""
    plain = re.sub(r"[^a-z0-9]", "", name.lower())
    dashed = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    for g in dict.fromkeys(x for x in (host.split(".")[0], plain, dashed) if x):
        if has_jobs("ashby", g):
            return g
    if host:
        for u in [f"https://{host}"] + [f"https://{host}{p}" for p in CAREER_PATHS]:
            r = _get(u)
            if r:
                for m in ATS_PATTERNS[0][1].finditer(r.text):
                    if m.group(1).lower() not in BAD_SLUGS and has_jobs("ashby", m.group(1)):
                        return m.group(1)
    return None


def build_ashby_extra() -> list[dict]:
    """Seed-to-Series-C companies from the VC directory (data/directory.json) that hire through Ashby -> data/ashby_extra.json.
    Ashby is where most startup ops / strategy / finance roles are posted, so the daily scan reads these boards directly."""
    from .vet import EARLY, Vetter, norm

    directory = json.loads((ROOT / "data" / "directory.json").read_text(encoding="utf-8"))
    vet = Vetter()
    cands = [c for c in directory if c.get("stage") in EARLY and not vet.is_healthcare(c["name"])
             and (c.get("head_count") or 0) <= 1500]

    def go(c):
        try:
            slug = _ashby_slug(c["name"], c.get("domain", ""))
        except Exception:
            slug = None
        return {"name": c["name"], "ats": "ashby", "slug": slug, "stage": c["stage"], "early": True} if slug else None

    found = []
    with cf.ThreadPoolExecutor(32) as ex:
        for i, x in enumerate(ex.map(go, cands), 1):
            if x:
                found.append(x)
            if i % 200 == 0:
                print(f"  ...{i}/{len(cands)} checked, {len(found)} on Ashby", flush=True)
    out = ROOT / "data" / "ashby_extra.json"
    out.write_text(json.dumps(found, indent=1), encoding="utf-8")
    return found
