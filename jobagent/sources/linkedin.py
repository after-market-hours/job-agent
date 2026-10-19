"""LinkedIn roles via your own LinkedIn job-alert emails.

LinkedIn can't be scraped reliably (login wall, bot blocking, terms of service), so instead you create saved-search
alerts on LinkedIn ("Chief of Staff", "Strategic Finance", ... location San Francisco / New York, "Past week", daily
email) and this source reads the alert emails from your Gmail inbox over IMAP (same app password as the digest).

For each job link found:
  1. title / company / location come from the email;
  2. title and location filters run BEFORE any page is fetched;
  3. the public job page is fetched best-effort for the description (visa, pay, experience) and the external apply link;
     if the apply link is an Ashby / Greenhouse / Lever posting the job is re-keyed to that posting, so it dedupes
     against the same role found directly on the company's board and gets the real form check.
Nothing is ever applied to from here.
"""
from __future__ import annotations

import email
import html
import imaplib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urlparse

import requests

from ..enrich import strip_html
from ..models import Job
from .describe import describe
from .speedrun import ATS_LINK

log = logging.getLogger("jobagent")

SENDERS = ["jobalerts-noreply@linkedin.com", "jobs-listings@linkedin.com", "jobs-noreply@linkedin.com"]
LOOKBACK_DAYS = 8
JOB_ID = re.compile(r"/jobs/view/(?:[^/?\"'\s<>]*?-)?(\d{8,})")
JUNK = re.compile(
    r"^(view job|apply|easy apply|see all jobs|actively recruiting|actively hiring|be an early applicant|promoted|"
    r"reposted|new|top job pick|\d+ (?:school alumni|connections?)|.*\bapplicants?\b.*|.*\bago$|\$.*|"
    r"with verification|responses? managed.*|unsubscribe.*|this email was.*)$", re.I)
UA = {"User-Agent": "Mozilla/5.0 (job-agent personal use)"}


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(t or "")).strip()


def _split_company_loc(line: str) -> tuple[str, str]:
    for sep in (" · ", " • ", " | "):
        if sep in line:
            a, b = line.split(sep, 1)
            return a.strip(), b.strip()
    return line.strip(), ""


def _details(lines: list[str]) -> tuple[str, str]:
    lines = [l for l in lines if l and not JUNK.match(l)]
    if not lines:
        return "", ""
    company, loc = _split_company_loc(lines[0])
    if not loc and len(lines) > 1:
        loc = lines[1]
    return company, loc


def parse_html(page: str) -> list[dict]:
    """Job cards from an alert email's HTML: a link whose href holds /jobs/view/<id> gives the title; the text that
    follows it (until the next job link) gives company and location."""
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    toks, cur = [], None            # ("A", id, text) for text inside a job link, ("T", text) otherwise
    for part in re.split(r"(<[^>]+>)", page):
        if part.startswith("<a ") or part.startswith("<A "):
            m = JOB_ID.search(html.unescape(part))
            cur = m.group(1) if m else None
        elif part.lower().startswith("</a"):
            cur = None
        elif part.startswith("<"):
            continue
        else:
            t = _clean(part)
            if t:
                toks.append(("A", cur, t) if cur else ("T", t))
    jobs, i = [], 0
    seen = set()
    while i < len(toks):
        tok = toks[i]
        if tok[0] == "A" and tok[1] not in seen and not JUNK.match(tok[2]):
            jid, title = tok[1], tok[2]
            j = i + 1
            rest = []
            while j < len(toks) and not (toks[j][0] == "A" and not JUNK.match(toks[j][2]) and toks[j][1] != jid):
                if toks[j][0] == "T":
                    rest.append(toks[j][1])
                j += 1
            company, loc = _details(rest[:6])
            seen.add(jid)
            jobs.append({"id": jid, "title": title, "company": company, "location": loc})
            i = j
        else:
            i += 1
    return jobs


def parse_text(body: str) -> list[dict]:
    """Plain-text alerts: title / company / location lines, then 'View job: <url>'."""
    jobs, seen = [], set()
    lines = [l.strip() for l in body.splitlines()]
    start = 0                      # only lines after the previous job's link belong to this job
    for n, line in enumerate(lines):
        m = JOB_ID.search(line)
        if not m:
            continue
        block, start = lines[start:n], n + 1
        if m.group(1) in seen:
            continue
        prev = [l for l in block if l and "http" not in l and not JUNK.match(l)][-3:]
        if prev and any(sep in prev[-1] for sep in (" · ", " • ", " | ")):
            prev = prev[-2:]           # "Company · Location" on one line
        if len(prev) == 3:
            title, company, loc = prev
        elif len(prev) == 2:
            title = prev[0]
            company, loc = _split_company_loc(prev[1])
        else:
            continue
        seen.add(m.group(1))
        jobs.append({"id": m.group(1), "title": title, "company": company, "location": loc})
    return jobs


def parse_message(msg) -> list[dict]:
    htmls, texts = [], []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            (htmls if ctype == "text/html" else texts).append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    jobs = [j for h in htmls for j in parse_html(h)]
    if not jobs:
        jobs = [j for t in texts for j in parse_text(t)]
    return [j for j in jobs if j["title"] and j["company"]]


def read_alerts() -> list[dict]:
    """All job cards from LinkedIn alert emails of the last LOOKBACK_DAYS days, with the email's date."""
    addr, pw = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
    if not addr or not pw or "xxxx" in pw:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
    out: dict[str, dict] = {}
    box = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        box.login(addr, pw.replace(" ", ""))
        mailbox = os.environ.get("LINKEDIN_MAILBOX", "INBOX")
        if box.select(f'"{mailbox}"', readonly=True)[0] != "OK":
            log.warning("linkedin: mailbox %s not found", mailbox)
            return []
        ids: list[bytes] = []
        for s in SENDERS:
            typ, data = box.search(None, f'(FROM "{s}" SINCE {since})')
            if typ == "OK" and data and data[0]:
                ids += data[0].split()
        for mid in sorted(set(ids), reverse=True):  # newest emails first, so a repeated job keeps its freshest date
            typ, data = box.fetch(mid, "(RFC822)")
            if typ != "OK" or not data or not data[0]:
                continue
            msg = email.message_from_bytes(data[0][1])
            try:
                sent = parsedate_to_datetime(msg["Date"]).astimezone(timezone.utc)
            except (TypeError, ValueError):
                sent = datetime.now(timezone.utc)
            for c in parse_message(msg):
                out.setdefault(c["id"], {**c, "sent": sent})
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return list(out.values())


def _guest_page(jid: str) -> str:
    try:
        r = requests.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}", headers=UA, timeout=20)
        return r.text if r.status_code == 200 else ""
    except requests.RequestException:
        return ""


def _external_apply(page: str) -> str:
    m = re.search(r'applyUrl[^>]*>\s*<!--\s*"([^"]+)"', page) or re.search(r'href="([^"]*externalApply[^"]*)"', page)
    if not m:
        return ""
    link = html.unescape(m.group(1))
    q = parse_qs(urlparse(link).query).get("url")
    return unquote(q[0]) if q else link


def _posted(page: str, sent: datetime) -> datetime:
    m = re.search(r'datetime="(\d{4}-\d\d-\d\d)', page)
    if m:
        try:
            return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    m = re.search(r"(\d+)\s+(hour|day|week|month)s?\s+ago", page)
    if m:
        days = int(m.group(1)) * {"hour": 0, "day": 1, "week": 7, "month": 30}[m.group(2)]
        return datetime.now(timezone.utc) - timedelta(days=days)
    return sent


def build(card: dict) -> Job:
    jid = card["id"]
    page = _guest_page(jid)
    time.sleep(0.5)  # be gentle: a handful of pages per day
    url = f"https://www.linkedin.com/jobs/view/{jid}"
    apply = _external_apply(page)
    ats, slug, ext = "linkedin", "linkedin", jid
    for name, rx in ATS_LINK:
        m = rx.search(apply)
        if m:
            ats, slug, ext = name, m.group(1), m.group(2)
            break
    if ats != "linkedin":
        desc = describe(apply)          # the company's own posting is the better source
    else:
        m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', page, re.S)
        desc = strip_html(m.group(1)) if m else ""
    return Job(ats=ats, slug=slug, ext_id=ext, company=card["company"], stage="", title=card["title"],
               url=apply if ats != "linkedin" else url, apply_url=apply or url, location=card["location"],
               posted_at=_posted(page, card["sent"]), description=desc)


def fetch_all() -> list[Job]:
    from ..pipeline import load_yaml
    from ..rank import location_ok, title_ok

    cfg = load_yaml("filters.yaml")
    try:
        cards = read_alerts()
    except (imaplib.IMAP4.error, OSError) as e:
        log.warning("linkedin alerts unreadable: %s", e)
        return []
    keep = [c for c in cards if title_ok(c["title"], cfg) and location_ok(f"{c['location']} {c['title']}", cfg)]
    log.info("linkedin: %d alert cards, %d pass title/location filters", len(cards), len(keep))
    return [build(c) for c in keep]
