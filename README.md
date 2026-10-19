# Job Agent

Daily email of fresh seed–Series C Chief of Staff / Strategy / Strategic Finance / GTM roles, an approval-gated apply tool, and a local tracker.

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
- `config/filters.yaml` — title keywords (incl. strategic finance / FP&A), max age (35 days), daily limit, non-US location exclusions. Plain business-operations titles ("Business Operations Manager", "Operations Associate") are dropped unless they also say strategy, CoS, GTM/revenue/sales/marketing ops or finance (`pure_ops_*`).
- Jobs that say they will not sponsor visas are dropped entirely; lone 6+ year minimums are dropped (ranges are kept).

## Company sources and vetting
- **Curated** (`config/companies.yaml`), **YC** (hiring, active, batch 2019+, <=200 people; refreshed with `harvest`, auto-run weekly), **a16z speedrun talent network** (searched for each target role), and any company website you add with
  `add-company "Name" https://their-site.com --stage seed` (finds their Ashby/Greenhouse/Lever board, or scans their own careers page).
- **Vetting** (`config/vetting.yaml`): public and Series C+ companies are never emailed. A company nobody has judged yet is **not emailed**; its name appears in the digest footer so it can be vetted.
- Custom careers pages: scanned by plain HTTP daily; JavaScript-only pages get a browser scan on Mondays.

## Ashby priority
Most startup roles live on Ashby, so Ashby-hosted roles rank 7 days "fresher" (`ashby_bonus_days`). `jobagent ashby` (weekly, in the refresh workflow) probes every seed–C company in the VC directory for an Ashby board and saves them to `data/ashby_extra.json`, which the daily scan reads.

## LinkedIn (via your job-alert emails)
LinkedIn blocks scraping, so the agent reads the alert emails LinkedIn sends you. One-time: on LinkedIn run job searches (e.g. "chief of staff", "strategic finance", "FP&A", "GTM operations"; United States or SF/NY; date posted: past week), click **Set alert** with daily email. Alerts from `jobalerts-noreply@linkedin.com` in your Gmail inbox are read over IMAP with the same app password (read-only; set `LINKEDIN_MAILBOX` if a filter files them in a label). Title/location filters run first, then the public job page is read for description/visa/pay, and an external Ashby/Greenhouse/Lever apply link is followed so the role dedupes against the company's own board. LinkedIn has no funding stage, so roles at companies not already known to be seed–C appear in their own section ("stage not verified", max 8).

## Digest layout (30 startups + 10 public)
- **Startups, seed to Series C** (30/day, stage shown on every row): Ready to auto-apply / Manual (custom questions) / Form not checked.
- **Public companies under $20B market cap** (10/day, live market cap from Yahoo Finance; edit `config/public_companies.yaml`).
- Emerging consumer / building-products / industrial brands from `data/watchlist.json` carry a blue tag with sector, headcount and a news-mention count (Google News, last 90 days) as a press-activity signal.
- Rebuild watchlists weekly (scheduled Sundays): `harvest` (YC) and `watchlist` (VC directory + emerging brands).
- **Applications are never automatic.** The digest and scheduled tasks never apply. `apply <id>` works only in an interactive terminal, shows exactly what it will submit, and submits only if you type `yes`.
