from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Job:
    ats: str
    slug: str
    ext_id: str
    company: str
    stage: str
    title: str
    url: str
    apply_url: str
    location: str
    posted_at: Optional[datetime]
    description: str = ""
    structured_comp: str = ""
    # filled by enrich
    comp_line: str = ""
    equity_line: str = ""
    visa_flag: str = "none"   # sponsors | auth_required | none | excluded
    visa_snippet: str = ""
    exp_line: str = ""
    exp_excluded: bool = False
    # filled by form check
    custom_questions: Optional[list] = None   # None = unchecked, [] = standard only

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.ats}:{self.slug}:{self.ext_id}".encode()).hexdigest()[:8]
