"""Company vetting: is this an early-stage private startup?

Order of evidence (first hit wins):
  1. config/vetting.yaml          manual verdicts (early | late | public) -- always wins
  2. config/companies.yaml        curated list with stage (seed/A/B)
  3. data/discovered.json         YC / harvested companies (batch year, team size, status)
  4. otherwise                    'unverified' -> still shown, but flagged for your judgment
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EARLY = {"seed", "A", "B", "YC"}


def norm(name: str) -> str:
    n = re.sub(r"\(.*?\)", "", (name or "").lower())
    n = re.sub(r"\b(inc|llc|ltd|corp|co|labs?|ai|hq|technologies|technology|the)\b\.?", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


class Vetter:
    def __init__(self):
        v = ROOT / "config" / "vetting.yaml"
        self.manual = {norm(k): d for k, d in (yaml.safe_load(v.read_text(encoding="utf-8")) or {}).items()} if v.exists() else {}
        c = yaml.safe_load((ROOT / "config" / "companies.yaml").read_text(encoding="utf-8")) or {}
        self.curated = {norm(x["name"]): x for x in c.get("companies", [])}
        d = ROOT / "data" / "discovered.json"
        self.discovered = {norm(x["name"]): x for x in json.loads(d.read_text(encoding="utf-8"))} if d.exists() else {}

    def verdict(self, name: str) -> tuple[str, str]:
        """Return (verdict, stage_label). verdict: early | late | public | unverified."""
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
        return "unverified", "unverified"
