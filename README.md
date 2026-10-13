# Job Agent

Daily email of ~20 fresh seed–Series B Chief of Staff / Strategy & Ops / GTM roles, an approval-gated apply tool, and a local tracker.

## One-time setup
1. Put your resume at `resume/resume.pdf` (and optionally a cover letter, set `cover_letter_path` in `config/profile.yaml`).
2. Fill in `config/profile.yaml` (phone, location, LinkedIn, work-auth answers).
3. Gmail: enable 2-step verification, create an App Password (https://myaccount.google.com/apppasswords), copy `.env.example` to `.env` and paste it.
4. Preview: `.venv\Scripts\python.exe -m jobagent digest --dry-run` then open `digest.html`.
5. Send for real: `.venv\Scripts\python.exe -m jobagent digest`
6. Schedule daily 8am: `powershell -ExecutionPolicy Bypass -File register_task.ps1`

## Daily use (run from this folder with `.venv\Scripts\python.exe -m jobagent ...`)
- `apply <id>` — opens a visible browser, fills the form, shows what it will submit, and only submits if you type `yes`. Forms with custom questions are refused and marked `manual`.
- `apply <id> --dry-run` — fill and preview, never submit.
- `status <id> interviewing|offer|rejected|skipped|manual|applied`
- `list [--state applied]`, `export` (writes `applications.xlsx`)

## Tuning
- `config/companies.yaml` — companies scanned (Ashby/Greenhouse/Lever slug + stage). Add more freely; stage labels are best-effort.
- `config/filters.yaml` — title keywords, max age, daily limit, non-US location exclusions.
- Jobs that say they will not sponsor visas are dropped entirely; lone 6+ year minimums are dropped (ranges are kept).

## Company sources and vetting
- **Curated** (`config/companies.yaml`), **YC** (hiring, active, batch 2019+, <=200 people; refreshed with `harvest`, auto-run weekly), **a16z speedrun talent network** (searched for each target role), and any company website you add with
  `add-company "Name" https://their-site.com --stage seed` (finds their Ashby/Greenhouse/Lever board, or scans their own careers page).
- **Vetting** (`config/vetting.yaml`): public and Series C+ companies are never emailed. A company nobody has judged yet is **not emailed**; its name appears in the digest footer so it can be vetted.
- Custom careers pages: scanned by plain HTTP daily; JavaScript-only pages get a browser scan on Mondays.

## Digest layout (30 startups + 10 public)
- **Startups, seed to Series C** (30/day, stage shown on every row): Ready to auto-apply / Manual (custom questions) / Form not checked.
- **Public companies under $20B market cap** (10/day, live market cap from Yahoo Finance; edit `config/public_companies.yaml`).
- Emerging consumer / building-products / industrial brands from `data/watchlist.json` carry a blue tag with sector, headcount and a news-mention count (Google News, last 90 days) as a press-activity signal.
- Rebuild watchlists weekly (scheduled Sundays): `harvest` (YC) and `watchlist` (VC directory + emerging brands).
- **Applications are never automatic.** The digest and scheduled tasks never apply. `apply <id>` works only in an interactive terminal, shows exactly what it will submit, and submits only if you type `yes`.
