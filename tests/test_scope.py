from datetime import datetime, timedelta, timezone

import pytest
import yaml

from jobagent.models import Job
from jobagent.rank import sort_key, title_ok
from jobagent.sources import linkedin

CFG = yaml.safe_load(open("config/filters.yaml", encoding="utf-8"))


@pytest.mark.parametrize("title", [
    "Strategic Finance Manager", "Strategic Finance & Operations", "FP&A Manager", "Finance & Strategy Lead",
    "Senior Strategic Finance Associate", "Corporate Finance Analyst", "Financial Planning and Analysis Manager",
    "Chief of Staff", "Chief of Staff to the CEO", "Strategy & Operations Manager", "Strategy and Business Operations",
    "GTM Operations Manager", "Revenue Operations Manager", "Sales Operations Lead", "Business Operations & Strategy",
    "Growth Operations Associate", "Operations Manager, GTM",
])
def test_titles_kept(title):
    assert title_ok(title, CFG)


@pytest.mark.parametrize("title", [
    "Business Operations Manager", "Business Operations Associate", "BizOps Lead", "Operations Manager",
    "Operations Associate", "Senior Operations Lead", "Ops Manager", "Business Operations Analyst",
    "Head of Strategic Finance", "VP, Finance", "Accounting Manager", "Controller, Finance", "Tax Manager",
    "Accounts Payable Specialist", "Senior Director, Strategic Finance",
])
def test_titles_dropped(title):
    assert not title_ok(title, CFG)


def _job(ats, age_days, title="Chief of Staff", loc="Austin, TX"):
    return Job(ats=ats, slug="x", ext_id="1", company="Acme", stage="A", title=title, url="", apply_url="", location=loc,
               posted_at=datetime.now(timezone.utc) - timedelta(days=age_days))


def test_ashby_ranks_ahead_of_equally_fresh_roles():
    assert sort_key(_job("ashby", 5)) < sort_key(_job("greenhouse", 5))
    assert sort_key(_job("ashby", 5)) < sort_key(_job("greenhouse", 1))     # a 4-day freshness gap is outweighed
    assert sort_key(_job("greenhouse", 5)) < sort_key(_job("linkedin", 5))  # LinkedIn copy loses ties to the board posting


def test_max_age_is_35_days():
    assert CFG["max_age_days"] == 35


HTML_ALERT = """
<html><body>
<a href="https://www.linkedin.com/comm/jobs/view/4012345678?trackingId=abc&amp;refId=x"><img src="logo.png"></a>
<a href="https://www.linkedin.com/comm/jobs/view/4012345678?trackingId=abc&amp;refId=x" style="x">Strategic Finance Manager</a>
<p>Acme Robotics</p><p>San Francisco, CA</p><p>Actively recruiting</p>
<a href="https://www.linkedin.com/comm/jobs/view/4012345678?trackingId=abc">View job</a>
<table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/?x=1">Chief of Staff</a></td></tr>
<tr><td>Beta Labs · New York, NY</td></tr><tr><td>2 days ago</td></tr></table>
<a href="https://www.linkedin.com/jobs/search?keywords=x">See all jobs</a>
</body></html>
"""

TEXT_ALERT = """Your job alert for strategic finance

Strategic Finance Manager
Acme Robotics
San Francisco, CA
View job: https://www.linkedin.com/comm/jobs/view/4012345678?trackingId=abc

Chief of Staff
Beta Labs · New York, NY
View job: https://www.linkedin.com/comm/jobs/view/4099999999?trackingId=def
"""


def test_parse_html_alert():
    jobs = linkedin.parse_html(HTML_ALERT)
    assert jobs == [
        {"id": "4012345678", "title": "Strategic Finance Manager", "company": "Acme Robotics", "location": "San Francisco, CA"},
        {"id": "4099999999", "title": "Chief of Staff", "company": "Beta Labs", "location": "New York, NY"},
    ]


def test_parse_text_alert():
    jobs = linkedin.parse_text(TEXT_ALERT)
    assert [(j["id"], j["title"], j["company"], j["location"]) for j in jobs] == [
        ("4012345678", "Strategic Finance Manager", "Acme Robotics", "San Francisco, CA"),
        ("4099999999", "Chief of Staff", "Beta Labs", "New York, NY"),
    ]


def test_slug_style_linkedin_urls():
    jobs = linkedin.parse_text("Chief of Staff\nBeta\nNew York\nhttps://www.linkedin.com/jobs/view/chief-of-staff-at-beta-4099999999?x=1")
    assert jobs and jobs[0]["id"] == "4099999999"


def test_external_apply_link_resolves_to_ats():
    page = ('<code id="applyUrl"><!--"https://www.linkedin.com/jobs/view/externalApply/4012345678?url='
            'https%3A%2F%2Fjobs.ashbyhq.com%2Facme%2F0b9a3f1e-1111-2222-3333-444455556666"--></code>')
    assert linkedin._external_apply(page).startswith("https://jobs.ashbyhq.com/acme/")
