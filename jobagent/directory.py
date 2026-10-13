"""Company directory + emerging-brand watchlist.

`build_directory()` pulls every portfolio company (with funding stage, headcount, industry tags, website) from the
Getro-powered VC boards. That directory (a) supplies funding stage for companies other sources don't label and
(b) is the pool for the watchlist: seed-to-Series-C consumer / retail / home / building-products / industrial
companies, whose own careers pages are then resolved and scanned directly (like Yardsale).

Press-activity signal: number of Google News items about the company in the last 90 days (a free proxy for press
velocity; LinkedIn follower counts can't be read without logging in).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import urllib.parse
from pathlib import Path

import requests

from .discover import resolve
from .sources.getro import BOARDS, H
from .vet import EARLY, norm

ROOT = Path(__file__).resolve().parent.parent
STAGE = {"pre_seed": "seed", "seed": "seed", "series_a": "A", "series_b": "B", "series_c": "C",
         "series_c_plus": "late", "series_d": "late", "series_e": "late", "series_f": "late", "series_g": "late",
         "series_h": "late", "series_i": "late", "ipo": "late", "acquisition": "late", "private_equity": "late"}

SECTORS = [  # (label, regex over tags + description)
    ("consumer / DTC", r"direct[- ]to[- ]consumer|\bdtc\b|\bd2c\b|consumer (?:goods|products|brand)|\bcpg\b|e-?commerce|retail"),
    ("apparel / footwear", r"apparel|fashion|footwear|clothing|outerwear|accessories"),
    ("food & beverage", r"food|beverage|snack|drink|grocery|restaurant|coffee|wine|spirits"),
    ("home / lifestyle", r"home goods|furniture|home decor|mattress|kitchen|pet\b|baby|outdoor|sporting|fitness equipment|toys?"),
    ("building products / construction", r"building products|building materials|construction|proptech|real estate tech|homebuilding|architecture|hvac|roofing|solar installation"),
    ("industrials / manufacturing", r"industrial|manufactur|robotics|hardware|supply chain|logistics|energy storage|battery|aerospace|materials"),
    ("beauty / wellness", r"beauty|skincare|cosmetic|personal care|wellness"),
]


def _companies(board: tuple) -> list[dict]:
    host, nid = board
    out = []
    total = None
    for page in range(400):  # the API returns 12 companies per page regardless of hitsPerPage
        try:
            r = requests.post(f"https://api.getro.com/api/v2/collections/{nid}/search/companies", headers=H, timeout=30,
                              json={"hitsPerPage": 12, "page": page, "query": "", "filters": {}})
            res = r.json()["results"]
            cos = res["companies"]
        except (requests.RequestException, ValueError, KeyError):
            break
        total = res.get("count", total)
        out += cos
        if not cos or (total is not None and len(out) >= total):
            break
    for c in out:
        c["_board"] = host
    return out


def build_directory() -> list[dict]:
    with cf.ThreadPoolExecutor(len(BOARDS)) as ex:
        raw = [c for res in ex.map(_companies, BOARDS) for c in res]
    merged: dict[str, dict] = {}
    for c in raw:
        key = norm(c["name"])
        stage = STAGE.get(c.get("stage") or "", "")
        e = merged.setdefault(key, {"name": c["name"], "domain": c.get("domain", ""), "stage": stage,
                                    "head_count": c.get("head_count"), "tags": [], "description": c.get("description", ""),
                                    "active_jobs": 0, "boards": []})
        e["tags"] = sorted(set(e["tags"]) | set(c.get("industry_tags") or []) | set(c.get("topics") or []))
        e["active_jobs"] = max(e["active_jobs"], c.get("active_jobs_count") or 0)
        e["boards"].append(c["_board"])
        e["stage"] = e["stage"] or stage
        e["head_count"] = e["head_count"] or c.get("head_count")
    out = list(merged.values())
    p = ROOT / "data" / "directory.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def sector_of(c: dict) -> str:
    text = " ".join(c.get("tags", [])) + " " + c.get("description", "")
    for label, rx in SECTORS:
        if re.search(rx, text, re.I):
            return label
    return ""


def press_count(name: str, days: int = 90) -> int | None:
    q = urllib.parse.quote(f'"{name}"')
    try:
        r = requests.get(f"https://news.google.com/rss/search?q={q}+when:{days}d&hl=en-US&gl=US&ceid=US:en",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        return r.text.count("<item>") if r.ok else None
    except requests.RequestException:
        return None


def build_watchlist(directory: list[dict] | None = None, max_beauty: int = 15) -> list[dict]:
    """Seed-to-Series-C consumer/industrial companies with a resolvable careers page."""
    if directory is None:
        directory = json.loads((ROOT / "data" / "directory.json").read_text(encoding="utf-8"))
    cands = []
    for c in directory:
        s = sector_of(c)
        if c["stage"] in EARLY and s and c.get("domain") and (c.get("head_count") or 0) <= 1500:
            cands.append({**c, "sector": s})
    # keep the list diverse: cap beauty/wellness so it doesn't crowd out building products / industrials / food
    beauty = [c for c in cands if c["sector"] == "beauty / wellness"][:max_beauty]
    cands = [c for c in cands if c["sector"] != "beauty / wellness"] + beauty

    def go(c):
        try:
            res = resolve(c["name"], c["domain"])
        except Exception:
            res = None
        if not res:
            return None
        return {**c, **res, "early": True, "press_90d": press_count(c["name"])}

    out = []
    with cf.ThreadPoolExecutor(32) as ex:
        for i, x in enumerate(ex.map(go, cands), 1):
            if x:
                out.append(x)
            if i % 100 == 0:
                print(f"  ...{i}/{len(cands)} checked, {len(out)} resolved", flush=True)
    p = ROOT / "data" / "watchlist.json"
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out
