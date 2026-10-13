from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import Job


def title_ok(title: str, cfg: dict) -> bool:
    t = title.lower()
    if not any(re.search(p, t) for p in cfg["include_title_patterns"]):
        return False
    return not any(re.search(p, t) for p in cfg["exclude_title_patterns"])


def age_days(j: Job) -> float:
    if not j.posted_at:
        return 9999
    return (datetime.now(timezone.utc) - j.posted_at).total_seconds() / 86400


PRIORITY_LOC = re.compile(r"san francisco|\bsf\b|bay area|new york|\bnyc\b|\bny\b|brooklyn", re.I)
PRIORITY_BONUS_DAYS = 14   # an SF/NY role ranks as if it were 14 days newer


def is_priority_loc(j: Job) -> bool:
    return bool(PRIORITY_LOC.search(j.location or ""))


def sort_key(j: Job):
    # newest first (SF/NY get a recency bonus); unknown dates last
    return age_days(j) - (PRIORITY_BONUS_DAYS if is_priority_loc(j) else 0)


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
