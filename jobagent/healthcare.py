"""Healthcare / medtech detection: such companies are dropped from every list."""
from __future__ import annotations

import re

# Strong signals: one hit in a company's industry tags / one-liner / description is enough.
_STRONG = re.compile(
    r"health ?care|health ?tech|digital health|health ?system|medtech|med-?tech|medical|clinical|clinic\b|clinician|"
    r"patients?\b|hospital|pharma|biotech|biopharma|therapeutics?|telehealth|tele-?medicine|life sciences|"
    r"\bhealth\b|\bdiagnostics?\b|\bgenomics?\b|\bmental health\b|\bpayers?\b.{0,20}\bproviders?\b",
    re.I,
)
# Job-description fallback: needs several hits so a stray "our health insurance" line does not trigger it.
_BODY = re.compile(
    r"health ?care (?:company|industry|system|provider|organization)|digital health|medtech|medical device|"
    r"\bpatients?\b|\bclinicians?\b|hospitals?|\bpharma\w*|biotech|clinical trials?|health systems?|telehealth|\bFDA\b|\bHIPAA\b",
    re.I,
)
_BENEFITS = re.compile(r"health,? dental|medical,? dental|health insurance|health benefits|health and wellness|medical benefits", re.I)


def tags_are_healthcare(tags: list[str] | None, text: str = "") -> bool:
    return bool(_STRONG.search(" ".join(tags or []) + " " + (text or "")))


def description_is_healthcare(description: str) -> bool:
    head = _BENEFITS.sub(" ", (description or "")[:4000])
    return len(_BODY.findall(head)) >= 3
