"""Public-company section: listed companies under a market-cap ceiling, scanned for the same target roles."""
from __future__ import annotations

import concurrent.futures as cf
import json
import time
from pathlib import Path

import yaml

from .discover import resolve
from .models import Job
from .sources import FETCHERS

ROOT = Path(__file__).resolve().parent.parent
RESOLVED = ROOT / "data" / "public_resolved.json"
CAPS = ROOT / "data" / "marketcaps.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def market_caps(tickers: list[str], max_age_s: int = 86400) -> dict:
    """Live market caps (USD) from Yahoo Finance, cached for a day."""
    cache = _load(CAPS)
    now = time.time()
    need = [t for t in tickers if t not in cache or now - cache[t].get("ts", 0) > max_age_s]
    if need:
        import yfinance as yf

        def get(t):
            try:
                fi = yf.Ticker(t).fast_info
                return t, float(fi["marketCap"])
            except Exception:
                return t, None

        with cf.ThreadPoolExecutor(8) as ex:
            for t, cap in ex.map(get, need):
                if cap:
                    cache[t] = {"cap": cap, "ts": now}
        CAPS.parent.mkdir(exist_ok=True)
        CAPS.write_text(json.dumps(cache), encoding="utf-8")
    return {t: cache[t]["cap"] for t in tickers if t in cache}


def fetch_jobs() -> tuple[list[Job], dict]:
    cfg = yaml.safe_load((ROOT / "config" / "public_companies.yaml").read_text(encoding="utf-8"))
    ceiling = cfg.get("max_market_cap_usd", 20e9)
    cos = cfg["companies"]
    caps = market_caps([c["ticker"] for c in cos])
    eligible = [c for c in cos if c["ticker"] in caps and caps[c["ticker"]] < ceiling]
    resolved = _load(RESOLVED)

    def get_source(c):
        key = c["ticker"]
        if key not in resolved:
            try:
                resolved[key] = resolve(c["name"], c["website"]) or {}
            except Exception:
                resolved[key] = {}
        return c, resolved[key]

    with cf.ThreadPoolExecutor(16) as ex:
        sources = list(ex.map(get_source, eligible))
    RESOLVED.write_text(json.dumps(resolved), encoding="utf-8")

    def fetch(item):
        c, src = item
        if not src:
            return []
        try:
            jobs = FETCHERS[src["ats"]]({**c, **src})
        except Exception:
            return []
        for j in jobs:
            j.kind = "public"
            j.stage = "Public"
            j.company = c["name"]
            j.badge = f"Public: {c['ticker']} · ${caps[c['ticker']] / 1e9:.1f}B market cap"
        return jobs

    with cf.ThreadPoolExecutor(8) as ex:
        jobs = [j for res in ex.map(fetch, sources) for j in res]
    stats = {"public_companies": len(eligible), "public_no_source": sum(1 for _, s in sources if not s),
             "public_over_cap": sum(1 for c in cos if c["ticker"] in caps and caps[c["ticker"]] >= ceiling),
             "public_no_cap": sum(1 for c in cos if c["ticker"] not in caps)}
    return jobs, stats
