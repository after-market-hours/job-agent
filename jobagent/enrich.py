"""Regex enrichment: visa flag, experience requirement, salary and equity lines."""
from __future__ import annotations

import html
import re

from .models import Job

_NEG = re.compile(
    r"(?:will not|won'?t|unable to|cannot|can'?t|do(?:es)? not|don'?t|not (?:able|in a position|currently able|willing) to|"
    r"are not|is not|isn'?t|aren'?t)\s+(?:\w+\s+){0,4}?(?:sponsor|provide (?:visa|work))"
    r"|no (?:visa |immigration |employment |work )?sponsorship"
    r"|without (?:requiring |the need for |needing )?(?:visa |immigration |employer )?sponsorship"
    r"|(?:not|never) (?:require|need)s? (?:\w+\s+){0,2}?sponsorship"
    r"|sponsorship (?:is )?(?:not |un)available"
    r"|unable to (?:offer|provide) (?:\w+\s+){0,2}sponsorship",
    re.I,
)
_POS = re.compile(
    r"visa sponsorship (?:is |may be )?(?:available|offered|provided)"
    r"|\bwe (?:can |will |do |may |are (?:able|happy|willing|open) to )?sponsor"
    r"|\bwill sponsor\b|\bcan sponsor\b|\bsponsor(?:s|ship)? (?:for )?(?:work )?visas?\b(?! (?:now|in the future))"
    r"|\bh-?1b\b|offer(?:s)? (?:visa )?sponsorship|sponsorship (?:is )?(?:available|offered|provided)",
    re.I,
)
_AUTH = re.compile(
    r"authori[sz]ed to work|work authori[sz]ation|eligib\w+ to work|legally (?:authori[sz]ed|permitted|entitled)|right to work",
    re.I,
)


def strip_html(s: str) -> str:
    s = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", s or "", flags=re.I | re.S)  # page code is not job text
    s = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s)


def _sentence(text: str, m: re.Match) -> str:
    start = max(text.rfind(". ", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
    ends = [i for i in (text.find(". ", m.end()), text.find("\n", m.end())) if i != -1]
    end = min(ends) + 1 if ends else len(text)
    return re.sub(r"\s+", " ", text[start:end]).strip()[:240]


def visa(text: str) -> tuple[str, str]:
    """Return (flag, snippet). flag: excluded | sponsors | auth_required | none."""
    m = _NEG.search(text)
    if m:
        return "excluded", _sentence(text, m)
    for m in _POS.finditer(text):
        sent = _sentence(text, m)
        if "?" in sent or re.search(r"\byou (?:now |currently )?(?:will )?(?:require|need)", sent, re.I):
            continue  # an application-form question, not a statement that they sponsor
        return "sponsors", sent
    for m in _AUTH.finditer(text):
        sent = _sentence(text, m)
        if "?" in sent:
            continue  # application-form question, not the company's own statement
        return "auth_required", sent
    return "none", ""


_RANGE = re.compile(r"(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*(?:years|yrs)", re.I)
_LONE = [
    re.compile(r"(\d{1,2})\s*\+\s*(?:years|yrs)", re.I),
    re.compile(r"(?:at least|minimum(?: of)?|min\.?)\s*(\d{1,2})\s*(?:\+\s*)?(?:years|yrs)", re.I),
    re.compile(r"(\d{1,2})\s*(?:years|yrs)(?:['’]s?)?\s*(?:of\s+)?(?:\w+\s+){0,3}?experience", re.I),
]


def experience(text: str, max_ok: int = 5) -> tuple[str, bool]:
    """Return (display line, excluded). Excludes only a lone minimum >= max_ok+1 with no range."""
    ranges = [(int(a), int(b)) for a, b in _RANGE.findall(text) if int(a) < int(b) <= 20]
    if ranges:
        a, b = ranges[0]
        return f"Exp: {a}–{b} yrs", False
    lone = sorted({int(n) for rx in _LONE for n in rx.findall(text) if 1 <= int(n) <= 20})
    if not lone:
        return "Exp: not stated", False
    lowest = lone[0]
    return f"Exp: {lowest}+ yrs", lowest > max_ok


_MONEY = re.compile(
    r"\$\s?\d{2,3}(?:,\d{3}|(?:\.\d)?\s?[kK])\s*(?:USD)?\s*(?:[-–—]|to)\s*\$?\s?\d{2,3}(?:,\d{3}|(?:\.\d)?\s?[kK])", re.I
)
_EQ = re.compile(r"\bequity\b|stock options?|\bRSUs?\b|\boptions\b|stock grants?|ownership stake", re.I)
_EQ_SKIP = re.compile(r"private equity|diversity|equity and inclusion|equal|inclusion|equity firm|home equity", re.I)


def comp(structured: str, text: str) -> str:
    if structured:
        first = structured.split("•")[0].strip()
        if re.search(r"\d", first) and "%" not in first:
            return first
    m = _MONEY.search(text)
    return m.group(0).strip() if m else "Salary not listed"


def equity(structured: str, text: str) -> str:
    if "Offers Equity" in (structured or ""):
        return "Offers equity"
    m = re.search(r"\d+(?:\.\d+)?%\s*(?:[-–]\s*\d+(?:\.\d+)?%)?", structured or "")
    if m:
        return f"Equity: {m.group(0)}"
    for m in _EQ.finditer(text):
        s = _sentence(text, m)
        if _EQ_SKIP.search(s):
            continue
        pct = re.search(r"\d+(?:\.\d+)?\s*%\s*(?:[-–]\s*\d+(?:\.\d+)?\s*%)?", s)
        return f"Equity: {pct.group(0).strip()}" if pct else "Equity mentioned"
    return "Equity not stated"


def enrich(job: Job, max_ok_years: int = 5) -> Job:
    text = job.description
    job.visa_flag, job.visa_snippet = visa(text)
    job.exp_line, job.exp_excluded = experience(text, max_ok_years)
    job.comp_line = comp(job.structured_comp, text)
    job.equity_line = equity(job.structured_comp, text)
    return job
