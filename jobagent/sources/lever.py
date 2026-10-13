from __future__ import annotations

import re

import requests

from ..models import Job
from ..util import parse_dt

LIST = "https://api.lever.co/v0/postings/{slug}?mode=json"


def fetch(company: dict) -> list[Job]:
    r = requests.get(LIST.format(slug=company["slug"]), timeout=30)
    r.raise_for_status()
    out = []
    for j in r.json():
        parts = [j.get("descriptionPlain", "")]
        for lst in j.get("lists", []):
            parts.append(lst.get("text", ""))
            parts.append(re.sub(r"<[^>]+>", "\n", lst.get("content", "")))
        parts.append(j.get("additionalPlain", ""))
        sal = j.get("salaryRange") or {}
        comp = ""
        if sal.get("min") and sal.get("max"):
            cur = "$" if sal.get("currency", "USD") == "USD" else sal.get("currency", "") + " "
            comp = f"{cur}{sal['min']:,.0f} – {cur}{sal['max']:,.0f}"
        out.append(Job(
            ats="lever", slug=company["slug"], ext_id=j["id"], company=company["name"],
            stage=company.get("stage", ""), title=(j.get("text") or "").strip(),
            url=j.get("hostedUrl", ""), apply_url=j.get("applyUrl", ""),
            location=(j.get("categories") or {}).get("location", "") or "",
            posted_at=parse_dt(j.get("createdAt")), description="\n".join(parts), structured_comp=comp,
        ))
    return out


def custom_questions(job: Job) -> list[str]:
    """Lever's apply page is plain HTML; custom questions render as cards[...] fields."""
    from . import is_standard
    r = requests.get(job.apply_url, timeout=30)
    r.raise_for_status()
    out = []
    for m in re.finditer(r'<li class="application-question custom-question">(.*?)</li>', r.text, re.S):
        block = m.group(1)
        label = re.sub(r"<[^>]+>", " ", block.split("</div>")[0])
        label = re.sub(r"\s+", " ", label).strip()
        if "required" in block.lower() and not is_standard(label):
            out.append(label[:120])
    return out
