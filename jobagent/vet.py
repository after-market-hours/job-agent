"""Company vetting: is this a private startup between seed and Series C?

Order of evidence (first hit wins):
  1. config/vetting.yaml          manual verdicts (early | late | public) -- always wins
  2. config/companies.yaml        curated list with stage
  3. data/discovered.json         YC companies (batch year, team size)
  4. data/directory.json          VC-portfolio company directory (funding stage from Getro boards)
  5. otherwise                    'unverified' -> not emailed (unless the job source itself carries a stage)
'early' means seed through Series C (the 'target' stage band). 'late' means Series D+ / not a startup.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EARLY = {"seed", "A", "B", "C"}
LABEL = {"seed": "Seed", "A": "Series A", "B": "Series B", "C": "Series C"}


def stage_label(stage: str) -> str:
    """Human label for the digest. YC companies show their batch (funding stage not confirmed)."""
    if not stage:
        return "stage unknown"
    if stage in LABEL:
        return LABEL[stage]
    if stage.startswith("YC"):
        return f"{stage} (funding stage not confirmed)"
    return stage


def norm(name: str) -> str:
    n = re.sub(r"\(.*?\)", "", (name or "").lower())
    n = re.sub(r"\b(inc|llc|ltd|corp|co|labs?|ai|hq|technologies|technology|the)\b\.?", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


class Vetter:
    def __init__(self):
        v = ROOT / "config" / "vetting.yaml"
        self.manual = {norm(k): d for k, d in (yaml.safe_load(v.read_text(encoding="utf-8")) or {}).items()} if v.exists() else {}
        c = yaml.safe_load((ROOT / "config" / "companies.yaml").read_text(encoding="utf-8")) or {}
        self.curated = {norm(x["name"]): x for x in c.get("companies", [])}
        self.discovered = {norm(x["name"]): x for x in _load(ROOT / "data" / "discovered.json")}
        self.directory = {norm(x["name"]): x for x in _load(ROOT / "data" / "directory.json")}
        self.watch = {norm(x["name"]): x for x in _load(ROOT / "data" / "watchlist.json")}

    def verdict(self, name: str) -> tuple[str, str]:
        """Return (verdict, stage). verdict: early | late | public | unverified."""
        k = norm(name)
        if k in self.manual:
            m = self.manual[k]
            return m["verdict"], m.get("stage", m["verdict"])
        if k in self.curated:
            st = self.curated[k].get("stage", "")
            return ("early" if st in EARLY else "late"), st
        if k in self.discovered:
            x = self.discovered[k]
            return ("early" if x.get("early") else "late"), x.get("stage", "YC")
        if k in self.directory:
            st = self.directory[k].get("stage", "")
            if st in EARLY:
                return "early", st
            if st == "late":
                return "late", "late"
        return "unverified", "unverified"

    def badge(self, name: str) -> str:
        """Tag for emerging consumer / building-products / industrial brands (judged from the company's industry tags only)."""
        w = self.watch.get(norm(name))
        if not w:
            return ""
        from .directory import sector_of
        sector = sector_of({"tags": w.get("tags", []), "description": ""})
        if not sector:
            return ""
        software_tags = {"Fintech", "Financial Services", "Telecommunications", "Financial Software", "Developer Tools", "Cybersecurity"}
        if sector.startswith(("industrials", "building")) and software_tags & set(w.get("tags", [])) and "Construction" not in w.get("tags", []):
            return ""  # software/fintech companies with a stray 'logistics' or 'hardware' tag are not industrial brands
        bits = [sector]
        if w.get("press_90d") is not None:
            bits.append(f"{w['press_90d']} news mentions in last 90d")
        return "Emerging brand · " + " · ".join(bits)
