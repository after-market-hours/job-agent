from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from . import db, digest, pipeline

ROOT = Path(__file__).resolve().parent.parent


def cmd_digest(a):
    con = db.connect()
    jobs, stats = pipeline.run(con, a.limit, persist=not a.dry_run)
    html = digest.render(jobs, stats)
    (ROOT / "digest.html").write_text(html, encoding="utf-8")
    print(f"{len(jobs)} jobs | stats: {stats}")
    if a.dry_run:
        print("dry run: wrote digest.html (jobs not saved, nothing sent)")
        return
    if jobs:
        digest.send(html, f"Job digest {date.today():%b %d}: {len(jobs)} new roles")
    if a.no_save:
        print("sent as a test: jobs NOT marked as seen, they will appear again in the next real digest")
        return
    for j in jobs:
        db.save_job(con, j, "emailed")
    con.commit()
    print("sent" if jobs else "nothing to send")


def cmd_list(a):
    con = db.connect()
    q, args = "SELECT id,state,company,title,posted_at,url FROM jobs", ()
    if a.state:
        q, args = q + " WHERE state=?", (a.state,)
    for r in con.execute(q + " ORDER BY posted_at DESC", args):
        print(f"{r['id']}  {r['state']:<12} {r['company']:<20} {r['title'][:50]:<50} {r['url']}")


def cmd_status(a):
    con = db.connect()
    db.set_state(con, a.id, a.state, a.note or "")
    print("ok")


def cmd_export(a):
    from openpyxl import Workbook
    con = db.connect()
    wb = Workbook()
    ws = wb.active
    ws.title = "Applications"
    cols = ["id", "state", "company", "title", "stage", "location", "posted_at", "applied_at", "comp_line",
            "equity_line", "visa_flag", "exp_line", "url", "notes"]
    ws.append(cols)
    for r in con.execute("SELECT * FROM jobs ORDER BY COALESCE(applied_at, first_seen) DESC"):
        ws.append([r[c] for c in cols])
    out = ROOT / "applications.xlsx"
    wb.save(out)
    print(f"wrote {out}")


def cmd_harvest(a):
    from . import discover
    found = discover.build_cache(a.limit)
    kinds = {}
    for c in found:
        kinds[c["ats"]] = kinds.get(c["ats"], 0) + 1
    print(f"resolved {len(found)} YC companies: {kinds} -> data/discovered.json")


def cmd_watchlist(a):
    from . import directory
    d = directory.build_directory()
    w = directory.build_watchlist(d)
    kinds = {}
    for c in w:
        kinds[c["ats"]] = kinds.get(c["ats"], 0) + 1
    print(f"directory: {len(d)} VC-backed companies; watchlist: {len(w)} emerging consumer/industrial brands {kinds}")


def cmd_add_company(a):
    import yaml
    from . import discover
    res = discover.resolve(a.name, a.url)
    if not res:
        raise SystemExit("Could not find a careers page or ATS for that site.")
    path = ROOT / "config" / "companies.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = {"name": a.name, "stage": a.stage, **res}
    cfg["companies"].append(entry)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, width=200), encoding="utf-8")
    print(f"added: {entry}")


def cmd_apply(a):
    from . import apply as ap
    ap.run(a.id, dry_run=a.dry_run)


def main(argv=None):
    load_dotenv(ROOT / ".env")
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, filename=ROOT / "logs" / "agent.log",
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="jobagent")
    sp = p.add_subparsers(required=True)
    d = sp.add_parser("digest")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--limit", type=int)
    d.add_argument("--no-save", action="store_true", help="send, but do not mark jobs as emailed (for testing)")
    d.set_defaults(f=cmd_digest)
    l = sp.add_parser("list")
    l.add_argument("--state")
    l.set_defaults(f=cmd_list)
    s = sp.add_parser("status")
    s.add_argument("id")
    s.add_argument("state")
    s.add_argument("--note")
    s.set_defaults(f=cmd_status)
    e = sp.add_parser("export")
    e.set_defaults(f=cmd_export)
    h = sp.add_parser("harvest")
    h.add_argument("--limit", type=int)
    h.set_defaults(f=cmd_harvest)
    wl = sp.add_parser("watchlist", help="rebuild the VC company directory + emerging consumer/industrial watchlist")
    wl.set_defaults(f=cmd_watchlist)
    ac = sp.add_parser("add-company")
    ac.add_argument("name")
    ac.add_argument("url")
    ac.add_argument("--stage", default="seed", help="seed|A|B")
    ac.set_defaults(f=cmd_add_company)
    ap = sp.add_parser("apply")
    ap.add_argument("id")
    ap.add_argument("--dry-run", action="store_true")
    ap.set_defaults(f=cmd_apply)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    sys.exit(main())
