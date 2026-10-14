from . import ashby, greenhouse, lever, more_ats, web

FETCHERS = {"ashby": ashby.fetch, "greenhouse": greenhouse.fetch, "lever": lever.fetch, "web": web.fetch,
            "gem": more_ats.gem, "rippling": more_ats.rippling, "workable": more_ats.workable, "bamboohr": more_ats.bamboohr}
FORM_CHECKERS = {"ashby": ashby.custom_questions, "greenhouse": greenhouse.custom_questions, "lever": lever.custom_questions,
                 "web": web.custom_questions, "gem": more_ats.no_form_check, "rippling": more_ats.no_form_check,
                 "workable": more_ats.no_form_check, "bamboohr": more_ats.no_form_check}

# Field titles that count as "standard" (auto-fillable) on any ATS.
STANDARD = (
    "name", "email", "phone", "resume", "cv", "cover letter", "linkedin", "website", "portfolio",
    "github", "twitter", "location", "city", "address", "pronoun",
    # yes/no work-auth questions: auto-fillable from profile.yaml (apply refuses if unset)
    "authorized to work", "authorised to work", "legally", "sponsorship", "visa", "eligible to work",
    "based in the united states", "based in the us", "how did you hear",
)


def is_standard(label: str) -> bool:
    l = (label or "").lower()
    return any(s in l for s in STANDARD)
