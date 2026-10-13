"""Fetch a job description from an arbitrary apply/job URL (ATS APIs first, then page JSON-LD, then page text)."""
from __future__ import annotations

import json
import re

import requests

from ..enrich import strip_html

UA = {"User-Agent": "Mozilla/5.0 (job-agent personal use)"}
_ashby_cache: dict = {}


def _ashby(slug: str, jid: str) -> str:
    if slug not in _ashby_cache:
        try:
            _ashby_cache[slug] = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=20).json().get("jobs", [])
        except (requests.RequestException, ValueError):
            _ashby_cache[slug] = []
    for j in _ashby_cache[slug]:
        if j.get("id") == jid:
            return j.get("descriptionPlain", "")
    return ""


def describe(url: str) -> str:
    if not url:
        return ""
    try:
        m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f\-]{36})", url)
        if m:
            return _ashby(m.group(1), m.group(2))
        m = re.search(r"(?:job-boards|boards)\.greenhouse\.io/([^/?#]+)/jobs/(\d+)", url)
        if m:
            j = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}", timeout=20).json()
            return strip_html(j.get("content", ""))
        m = re.search(r"jobs\.lever\.co/([^/?#]+)/([0-9a-f\-]{36})", url)
        if m:
            j = requests.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}", timeout=20).json()
            return j.get("descriptionPlain", "") + "\n" + j.get("additionalPlain", "")
        page = requests.get(url, headers=UA, timeout=25).text
    except (requests.RequestException, ValueError):
        return ""
    for blob in re.findall(r'application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, dict) and x.get("@type") == "JobPosting" and x.get("description"):
                return strip_html(x["description"])
    return strip_html(page)[:20000]
