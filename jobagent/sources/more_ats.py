"""Extra applicant-tracking systems with public job feeds: Gem, Rippling, Workable, BambooHR.

Gem returns full postings (Greenhouse-style). Rippling, Workable and BambooHR return a list, then a per-job detail call
supplies the description. Rippling and BambooHR don't expose a post date, so the first-seen date is used (the tracker
dedupes, so a role is reported once).
"""
from __future__ import annotations

import concurrent.futures as cf
import re
from datetime import datetime, timezone

import requests

from ..enrich import strip_html
from ..models import Job
from ..util import parse_dt

H = {"User-Agent": "Mozilla/5.0 (job-agent personal use)", "Accept": "application/json"}


def _now():
    return datetime.now(timezone.utc)


def _mk(ats, company, ext, title, url, loc, posted, desc="", comp=""):
    return Job(ats=ats, slug=company["slug"], ext_id=str(ext), company=company["name"], stage=company.get("stage", ""),
               title=(title or "").strip(), url=url, apply_url=url, location=loc or "", posted_at=posted or _now(),
               description=desc, structured_comp=comp)


# ---- Gem --------------------------------------------------------------------------------------------------------
def gem(company: dict) -> list[Job]:
    r = requests.get(f"https://api.gem.com/job_board/v0/{company['slug']}/job_posts/", headers=H, timeout=30)
    r.raise_for_status()
    out = []
    for j in r.json():
        loc = (j.get("location") or {}).get("name", "") if isinstance(j.get("location"), dict) else ""
        out.append(_mk("gem", company, j.get("id"), j.get("title"), j.get("absolute_url", ""), loc,
                       parse_dt(j.get("first_published_at") or j.get("updated_at")), strip_html(j.get("content", ""))))
    return out


# ---- Rippling ---------------------------------------------------------------------------------------------------
def rippling(company: dict) -> list[Job]:
    base = f"https://api.rippling.com/platform/api/ats/v1/board/{company['slug']}/jobs"
    r = requests.get(base, headers=H, timeout=30)
    r.raise_for_status()
    rows = r.json()

    def one(j):
        desc = ""
        try:
            d = requests.get(f"{base}/{j['uuid']}", headers=H, timeout=25).json()
            desc = strip_html((d.get("description") or {}).get("company", "") + "\n" + (d.get("description") or {}).get("role", "")
                              if isinstance(d.get("description"), dict) else str(d.get("description", "")))
        except (requests.RequestException, ValueError):
            pass
        return _mk("rippling", company, j["uuid"], j.get("name"), j.get("url", ""), (j.get("workLocation") or {}).get("label", ""),
                   None, desc)

    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(one, rows))


# ---- Workable ---------------------------------------------------------------------------------------------------
def workable(company: dict) -> list[Job]:
    slug = company["slug"]
    r = requests.post(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", headers=H, timeout=30,
                      json={"query": "", "location": [], "department": [], "worktype": [], "remote": []})
    r.raise_for_status()
    rows = r.json().get("results", [])

    def one(j):
        desc = ""
        try:
            d = requests.get(f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{j['shortcode']}", headers=H, timeout=25).json()
            desc = strip_html(d.get("description", "") + "\n" + d.get("requirements", "") + "\n" + d.get("benefits", ""))
        except (requests.RequestException, ValueError):
            pass
        loc = j.get("location") or {}
        where = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x) + (" (Remote)" if j.get("remote") else "")
        return _mk("workable", company, j["shortcode"], j.get("title"), f"https://apply.workable.com/{slug}/j/{j['shortcode']}/",
                   where, parse_dt(j.get("published")), desc)

    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(one, rows))


# ---- BambooHR ---------------------------------------------------------------------------------------------------
def bamboohr(company: dict) -> list[Job]:
    slug = company["slug"]
    r = requests.get(f"https://{slug}.bamboohr.com/careers/list", headers=H, timeout=30)
    r.raise_for_status()
    rows = r.json().get("result", [])

    def one(j):
        desc, posted = "", None
        try:
            d = requests.get(f"https://{slug}.bamboohr.com/careers/{j['id']}/detail", headers=H, timeout=25).json()
            op = (d.get("result") or {}).get("jobOpening") or {}
            desc = strip_html(op.get("description", ""))
            posted = parse_dt(op.get("datePosted"))
        except (requests.RequestException, ValueError):
            pass
        loc = j.get("location") or {}
        where = ", ".join(x for x in (loc.get("city"), loc.get("state")) if x) + (" (Remote)" if j.get("isRemote") else "")
        return _mk("bamboohr", company, j["id"], j.get("jobOpeningName"), f"https://{slug}.bamboohr.com/careers/{j['id']}", where,
                   posted, desc)

    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(one, rows))


def no_form_check(job: Job):
    return None  # these application forms are checked when you run `apply`
