from __future__ import annotations

import requests

from ..models import Job
from ..util import parse_dt

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
GQL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting"
QUERY = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    id applicationForm { sections { fieldEntries { id field isRequired } } }
  }
}"""


def fetch(company: dict) -> list[Job]:
    r = requests.get(API.format(slug=company["slug"]), timeout=30)
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        if not j.get("isListed", True):
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary", "") or ""
        jobs.append(Job(
            ats="ashby", slug=company["slug"], ext_id=j["id"], company=company["name"],
            stage=company.get("stage", ""), title=(j.get("title") or "").strip(),
            url=j.get("jobUrl", ""), apply_url=j.get("applyUrl", ""),
            location=j.get("location", "") + (" (Remote)" if j.get("isRemote") else ""),
            posted_at=parse_dt(j.get("publishedAt")),
            description=j.get("descriptionPlain") or "", structured_comp=comp,
        ))
    return jobs


def custom_questions(job: Job) -> list[str]:
    from . import is_standard
    r = requests.post(GQL, json={"operationName": "ApiJobPosting", "query": QUERY, "variables": {
        "organizationHostedJobsPageName": job.slug, "jobPostingId": job.ext_id}}, timeout=30)
    r.raise_for_status()
    posting = (r.json().get("data") or {}).get("jobPosting")
    if not posting:
        raise RuntimeError("no jobPosting in response")
    out = []
    for sec in posting["applicationForm"]["sections"]:
        for e in sec["fieldEntries"]:
            f = e["field"]
            title = f.get("title") or ""
            if f.get("path", "").startswith("_systemfield_") or is_standard(title):
                continue
            if e.get("isRequired"):
                out.append(title)
    return out
