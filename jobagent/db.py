from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "jobs.db"

STATES = ["new", "emailed", "approved", "applied", "manual", "interviewing", "offer", "rejected", "skipped"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, ats TEXT, slug TEXT, ext_id TEXT, company TEXT, stage TEXT, title TEXT,
  url TEXT, apply_url TEXT, location TEXT, posted_at TEXT, comp_line TEXT, equity_line TEXT,
  visa_flag TEXT, visa_snippet TEXT, exp_line TEXT, custom_questions TEXT,
  state TEXT DEFAULT 'new', first_seen TEXT, emailed_at TEXT, applied_at TEXT, notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS history (
  job_id TEXT, state TEXT, at TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, reason TEXT, at TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def known_ids(con) -> set[str]:
    a = {r[0] for r in con.execute("SELECT id FROM jobs")}
    b = {r[0] for r in con.execute("SELECT id FROM seen")}
    return a | b


def mark_seen(con, job_id: str, reason: str):
    con.execute("INSERT OR IGNORE INTO seen VALUES (?,?,?)", (job_id, reason, now()))


def save_job(con, j: Job, state: str = "new"):
    import json
    con.execute(
        "INSERT OR IGNORE INTO jobs (id,ats,slug,ext_id,company,stage,title,url,apply_url,location,posted_at,comp_line,"
        "equity_line,visa_flag,visa_snippet,exp_line,custom_questions,state,first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (j.id, j.ats, j.slug, j.ext_id, j.company, j.stage, j.title, j.url, j.apply_url, j.location,
         j.posted_at.isoformat() if j.posted_at else None, j.comp_line, j.equity_line, j.visa_flag, j.visa_snippet,
         j.exp_line, None if j.custom_questions is None else json.dumps(j.custom_questions), state, now()),
    )
    con.execute("INSERT INTO history VALUES (?,?,?,?)", (j.id, state, now(), "saved"))


def set_state(con, job_id: str, state: str, note: str = ""):
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    cur = con.execute("UPDATE jobs SET state=? WHERE id=?", (state, job_id))
    if cur.rowcount == 0:
        raise KeyError(f"unknown job id {job_id}")
    if state == "applied":
        con.execute("UPDATE jobs SET applied_at=? WHERE id=?", (now(), job_id))
    if state == "emailed":
        con.execute("UPDATE jobs SET emailed_at=? WHERE id=?", (now(), job_id))
    con.execute("INSERT INTO history VALUES (?,?,?,?)", (job_id, state, now(), note))
    con.commit()
