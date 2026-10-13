"""Approval-gated application filler (Playwright, visible browser).

Flow: open form -> scan fields -> refuse if any required field isn't standard/answerable ->
fill -> screenshot -> user types 'yes' -> submit -> user confirms outcome -> tracker updated.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from . import db

ROOT = Path(__file__).resolve().parent.parent

SCAN_JS = """
() => {
  const out = [];
  const els = document.querySelectorAll('input, textarea, select');
  let i = 0;
  for (const el of els) {
    const t = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(t)) continue;
    const vis = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    if (!vis && t !== 'file') continue;
    let label = '';
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) label = l.innerText; }
    if (!label) { const l = el.closest('label'); if (l) label = l.innerText; }
    if (!label) label = el.getAttribute('aria-label') || '';
    if (!label) {
      const lb = el.getAttribute('aria-labelledby');
      if (lb) label = lb.split(' ').map(id => (document.getElementById(id) || {}).innerText || '').join(' ');
    }
    if (!label) {
      const wrap = el.closest('fieldset, [class*="field"], [class*="question"], li, div');
      if (wrap) { const l = wrap.querySelector('label, legend'); if (l) label = l.innerText; }
    }
    if (!label) label = el.placeholder || el.name || '';
    const required = el.required || el.getAttribute('aria-required') === 'true' || /\\*|required/i.test(label);
    el.setAttribute('data-ja-idx', String(i));
    const opts = el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()) : [];
    out.push({idx: i, type: t, tag: el.tagName.toLowerCase(), name: el.name || '', role: el.getAttribute('role') || '', label: label.replace(/\\s+/g, ' ').trim(), required, opts});
    i++;
  }
  return out;
}
"""


def load_profile() -> dict:
    return yaml.safe_load((ROOT / "config" / "profile.yaml").read_text(encoding="utf-8")) or {}


def _yn(v):
    return None if v is None else ("Yes" if v else "No")


def answer_for(f: dict, p: dict):
    """Return ('file'|'text'|'choice'|'skip'|'manual', value). 'manual' = needs a human."""
    lab = f["label"].lower()
    t = f["type"]
    if not lab.strip() and t != "file":
        return "skip", None  # unlabeled helper inputs (e.g. react-select internals)
    if len(lab) > 100 and not re.search(r"authori[sz]ed|sponsor|visa", lab):
        return ("manual", None) if f["required"] else ("skip", None)  # consent/essay-style prompts
    if t == "file":
        if "cover" in lab:
            cl = p.get("cover_letter_path")
            return ("file", str(ROOT / cl)) if cl else ("skip", None)
        return ("file", str(ROOT / p["resume_path"]))
    rules = [
        (r"first name|given name", p.get("first_name")),
        (r"last name|family name|surname", p.get("last_name")),
        (r"full name|legal name|^name\b|your name", f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()),
        (r"e-?mail", p.get("email")),
        (r"phone|mobile", p.get("phone")),
        (r"linkedin", p.get("linkedin")),
        (r"website|portfolio|personal site|github", p.get("website")),
        (r"location|city|where .*(based|working)", p.get("location")),
    ]
    for rx, val in rules:
        if re.search(rx, lab):
            return ("text", val) if val else ("manual" if f["required"] else "skip", None)
    if re.search(r"^country", lab):
        return ("choice", p.get("country") or "United States")
    if re.search(r"authori[sz]ed to work|legally (authori[sz]ed|permitted)|eligible to work|work in the (us|u\.s|united states)", lab):
        v = _yn(p.get("authorized_to_work_us"))
        return ("choice", v) if v else ("manual", None)
    if re.search(r"sponsor|visa", lab):
        v = _yn(p.get("requires_sponsorship"))
        return ("choice", v) if v else ("manual", None)
    if re.search(r"gender|race|ethnic|veteran|disabilit|hispanic|pronoun|sexual orientation", lab):
        # voluntary EEO: pick a 'decline' option in dropdowns; leave checkboxes/radios untouched
        return ("decline", None) if f["tag"] == "select" else ("skip", None)
    if re.search(r"how did you (hear|find)", lab):
        return ("skip", None) if not f["required"] else ("manual", None)
    return ("manual", None) if f["required"] else ("skip", None)


def _fill(page, f: dict, kind: str, val):
    loc = page.locator(f'[data-ja-idx="{f["idx"]}"]')
    if kind == "file":
        loc.set_input_files(val)
    elif kind == "text":
        loc.fill(val)
    elif kind == "choice":
        if f["role"] == "combobox":
            loc.click()
            loc.fill(val)
            page.wait_for_timeout(400)
            loc.press("Enter")
        elif f["tag"] == "select":
            opt = next((o for o in f["opts"] if o.lower().startswith(val.lower())), None)
            if opt:
                loc.select_option(label=opt)
        elif f["type"] == "radio":
            page.get_by_label(re.compile(rf"^{val}$", re.I)).first.check()
        else:
            loc.fill(val)
    elif kind == "decline" and f["tag"] == "select":
        opt = next((o for o in f["opts"] if re.search(r"decline|prefer not|do not wish", o, re.I)), None)
        if opt:
            loc.select_option(label=opt)


def run(job_id: str, dry_run: bool = False):
    from playwright.sync_api import sync_playwright

    con = db.connect()
    row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown job id {job_id}. Use `list` to see ids.")
    p = load_profile()
    resume = ROOT / p["resume_path"]
    if not resume.exists():
        raise SystemExit(f"Resume not found at {resume}. Put your PDF there or edit config/profile.yaml.")
    if not dry_run and not sys.stdin.isatty():
        # Safety: a scheduled task / script can never submit an application. Only a person at a terminal can.
        raise SystemExit("Refusing to submit: apply needs an interactive terminal where you type 'yes'. Use --dry-run to preview.")
    print(f"{row['title']} @ {row['company']}\n{row['apply_url']}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(row["apply_url"], wait_until="networkidle")
        fields = page.evaluate(SCAN_JS)
        plan, manual = [], []
        for f in fields:
            kind, val = answer_for(f, p)
            if kind == "manual":
                manual.append(f["label"] or f["name"])
            elif kind != "skip":
                plan.append((f, kind, val))
        if not manual and not any(kind == "file" for _, kind, _ in plan):
            # e.g. a company page whose 'Apply' button opens a Google Form, or only a newsletter box is present
            print("\nNo application form with a resume upload on this page (the apply button may open an external form).")
            print(f"Apply yourself: {row['apply_url']}")
            db.set_state(con, job_id, "manual", "no auto-fillable form on page")
            input("Press Enter to close the browser.")
            browser.close()
            return
        if manual:
            print("\nCannot auto-apply: these required fields need you:")
            for m in manual:
                print(f"  - {m}")
            print("Marked 'manual' in the tracker. Finish it yourself in the open browser, then press Enter.")
            db.set_state(con, job_id, "manual", "; ".join(manual)[:500])
            input()
            browser.close()
            return
        for f, kind, val in plan:
            _fill(page, f, kind, val)
        shot = ROOT / "data" / f"preview_{job_id}.png"
        page.screenshot(path=str(shot), full_page=True)
        print("\nWill submit:")
        for f, kind, val in plan:
            shown = Path(val).name if kind == "file" else (val or "(decline)")
            print(f"  {f['label'][:50]:<50} -> {shown}")
        print(f"Preview screenshot: {shot}")
        if dry_run:
            print("\n--dry-run: not submitting. Review the browser, then press Enter to close.")
            input()
            browser.close()
            return
        if input("\nType 'yes' to submit this application: ").strip().lower() != "yes":
            print("Not submitted.")
            browser.close()
            return
        btn = page.get_by_role("button", name=re.compile(r"submit|apply", re.I)).last
        btn.click()
        page.wait_for_timeout(4000)
        page.screenshot(path=str(ROOT / "data" / f"result_{job_id}.png"), full_page=True)
        ok = input("Did the confirmation page appear? (y/n): ").strip().lower() == "y"
        db.set_state(con, job_id, "applied" if ok else "manual", "submitted via agent" if ok else "submit unconfirmed")
        browser.close()
        print("Recorded as applied." if ok else "Marked manual - check the form.")
