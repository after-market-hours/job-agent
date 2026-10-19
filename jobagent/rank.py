from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import Job


def title_ok(title: str, cfg: dict) -> bool:
    t = title.lower()
    if not any(re.search(p, t) for p in cfg["include_title_patterns"]):
        return False
    if any(re.search(p, t) for p in cfg["exclude_title_patterns"]):
        return False
    return not is_pure_ops(t, cfg)


def is_pure_ops(title: str, cfg: dict) -> bool:
    """A plain business-operations role: matches a pure-ops pattern and none of the keep terms (strategy, GTM, finance...)."""
    t = title.lower()
    if not any(re.search(p, t) for p in cfg.get("pure_ops_patterns", [])):
        return False
    return not any(re.search(p, t) for p in cfg.get("pure_ops_keep_patterns", []))


def age_days(j: Job) -> float:
    if not j.posted_at:
        return 9999
    return (datetime.now(timezone.utc) - j.posted_at).total_seconds() / 86400


PRIORITY_LOC = re.compile(r"san francisco|\bsf\b|bay area|new york|\bnyc\b|\bny\b|brooklyn", re.I)
PRIORITY_BONUS_DAYS = 14   # an SF/NY role ranks as if it were 14 days newer


def is_priority_loc(j: Job) -> bool:
    return bool(PRIORITY_LOC.search(j.location or ""))


CORE_TITLE = re.compile(r"chief of staff|strateg|\bgtm\b|go[- ]to[- ]market|biz ?ops|business operations|revenue operations|rev ?ops|founder|financ", re.I)
GENERIC_PENALTY_DAYS = 10  # a plain 'Operations Associate' ranks as if it were 10 days older than a core role


ASHBY_BONUS_DAYS = 7        # overridden from filters.yaml (ashby_bonus_days) by the pipeline


def sort_key(j: Job):
    # newest first; SF/NY and Ashby-hosted roles get a recency bonus; generic ops titles a small penalty; unknown dates last;
    # a LinkedIn copy ranks just behind the same role found on the company's own ATS
    return (age_days(j) - (PRIORITY_BONUS_DAYS if is_priority_loc(j) else 0)
            - (ASHBY_BONUS_DAYS if j.ats == "ashby" else 0)
            + (0.5 if j.ats == "linkedin" else 0)
            + (0 if CORE_TITLE.search(j.title) else GENERIC_PENALTY_DAYS))


def posted_label(j: Job) -> str:
    d = age_days(j)
    if d == 9999:
        return "date unknown"
    if d < 1:
        return "today"
    return f"{int(d)}d ago"


def location_ok(loc: str, cfg: dict) -> bool:
    l = (loc or "").lower()
    bad = any(re.search(p, l) for p in cfg.get("exclude_location_patterns", []))
    good = any(re.search(p, l) for p in cfg.get("location_override_patterns", []))
    return good or not bad
