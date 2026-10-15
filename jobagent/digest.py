from __future__ import annotations

import os
import smtplib
import ssl
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from .models import Job
from .rank import posted_label
from .vet import stage_label

VISA = {
    "sponsors": ("✅ Mentions visa sponsorship", "#1a7f37"),
    "auth_required": ("⚠️ US work authorization required; sponsorship not stated", "#9a6700"),
    "none": ("❓ No visa / work-authorization mention", "#57606a"),
}


def _row(j: Job) -> str:
    label, color = VISA.get(j.visa_flag, VISA["none"])
    snippet = ""
    if j.visa_snippet:
        snippet = f'<div style="color:#57606a;font-size:12px">“{escape(j.visa_snippet)}”</div>'
    cq = ""
    if j.custom_questions:
        qs = "; ".join(escape(q[:80]) for q in j.custom_questions[:4])
        cq = f'<div style="font-size:12px;color:#9a3412">Custom questions: {qs}</div>'
    badge = f'<div style="font-size:12px;color:#0969da">{escape(j.badge)}</div>' if j.badge else ""
    stage = escape(stage_label(j.stage)) if j.kind == "private" else "Public company"
    return (
        '<tr><td style="padding:10px 0;border-bottom:1px solid #d0d7de">'
        f'<a href="{escape(j.url)}" style="font-size:15px;font-weight:600">{escape(j.title)}</a> — {escape(j.company)} '
        f'<span style="color:#57606a">({stage}) · {escape(j.location)} · {posted_label(j)}</span><br>'
        f'<span style="color:{color}">{label}</span>{snippet}'
        f'<div>💰 {escape(j.comp_line)} · {escape(j.equity_line)} · {escape(j.exp_line)}</div>{badge}{cq}'
        f'<div style="font-size:12px;color:#57606a">id: <code>{j.id}</code></div></td></tr>'
    )


def _section(title: str, sub: str, items: list[Job]) -> str:
    if not items:
        return ""
    rows = "".join(_row(j) for j in items)
    return (f"<h3>{title} ({len(items)})</h3>"
            f'<p style="color:#57606a;margin-top:-8px">{sub}</p><table width="100%">{rows}</table>')


def render(jobs: list[Job], stats: dict) -> str:
    priv = [j for j in jobs if j.kind == "private"]
    pub = [j for j in jobs if j.kind == "public"]
    ready = [j for j in priv if j.custom_questions == []]
    manual = [j for j in priv if j.custom_questions]
    unchecked = [j for j in priv if j.custom_questions is None]
    body = (
        f"<h2 style='border-bottom:2px solid #d0d7de'>Startups, seed to Series C ({len(priv)})</h2>"
        + _section("Ready to auto-apply", "Standard fields only. Nothing is ever submitted without your approval: "
                   "run <code>apply &lt;id&gt;</code> and type yes.", ready)
        + _section("Manual / custom questions", "Apply in your own time.", manual)
        + _section("Form not checked", "Will be checked when you run apply.", unchecked)
    )
    if not priv:
        body += "<p>No new matching startup roles today.</p>"
    body += _section("Public companies under $20B market cap", "Same role criteria; stock-listed employers.", pub) if pub else \
        "<h3>Public companies under $20B market cap</h3><p>No new matching roles today.</p>"
    foot = (f'<p style="color:#57606a;font-size:12px">Scanned {stats["companies"]} companies plus VC job boards '
            f'({stats["fetched"]} postings). Excluded: {stats["no_sponsorship"]} no-sponsorship, '
            f'{stats["exp_6plus"]} requiring 6+ yrs, {stats.get("not_early_stage", 0)} at later-stage companies, {stats.get("healthcare", 0)} healthcare, {stats.get("low_salary", 0)} under $100k.</p>')
    return (f'<html><body style="font-family:Segoe UI,Arial,sans-serif;max-width:760px">'
            f"<h2>Job digest · {date.today():%b %d}</h2>{body}{foot}</body></html>")


def send(html: str, subject: str):
    addr, pw = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
    if not addr or not pw or "xxxx" in pw:
        raise RuntimeError("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, addr, addr
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(addr, pw.replace(" ", ""))
        s.send_message(msg)
