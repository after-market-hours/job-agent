from __future__ import annotations

import requests

from ..enrich import strip_html
from ..models import Job
from ..util import parse_dt

LIST = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
ONE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}?questions=true"


def fetch(company: dict) -> list[Job]:
    r = requests.get(LIST.format(slug=company["slug"]), timeout=30)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        url = j.get("absolute_url", "")
        out.append(Job(
            ats="greenhouse", slug=company["slug"], ext_id=str(j["id"]), company=company["name"],
            stage=company.get("stage", ""), title=(j.get("title") or "").strip(), url=url, apply_url=url,
            location=(j.get("location") or {}).get("name", ""),
            posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
            description=strip_html(j.get("content") or ""),
        ))
    return out


def custom_questions(job: Job) -> list[str]:
    from . import is_standard
    r = requests.get(ONE.format(slug=job.slug, id=job.ext_id), timeout=30)
    r.raise_for_status()
    out = []
    for q in r.json().get("questions", []):
        label = q.get("label", "")
        if q.get("required") and not is_standard(label):
            out.append(label)
    return out
