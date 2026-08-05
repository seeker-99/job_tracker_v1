# Job Tracker

Daily automated monitor for 50+ career pages. Scrapes with Playwright, diffs
against a SQLite history using content hashes, and emails you a summary of
NEW / UPDATED / REMOVED postings that match your role and location filters.

## Read this first: what's real vs. what needs your input

This is a complete, working pipeline — SQLite storage, hashing/diffing,
retry logic, HTML+Markdown reports, email, Docker, and a GitHub Actions cron
job are all implemented and functional out of the box.

**The one thing I could not do for you:** verify live CSS selectors against
all 50 career pages. I don't have a browser session against those sites, and
many of them (Oracle Cloud HCM, custom React SPAs, Cloudflare-fronted pages)
render job listings in ways that change per-tenant. So:

- 15 sites use **platform-aware strategies** (Greenhouse, Workday, Oracle
  Cloud HCM, Zoho Recruit, Darwinbox, Avature, Mokahr) that work across most
  tenants of that platform without per-site tuning.
- The rest (`ats_type: generic`) ship with reasonable default selectors that
  will work on many sites but are **not guaranteed** to match every one on
  day one.
- I built `src/discover_selectors.py` specifically so you can fix any site
  that doesn't return results in under a minute, without reading raw HTML
  by hand. See "Tuning a site" below.
- `linkedin` (Humyn Labs) is disabled by default (`active: false`) because
  LinkedIn requires authentication and actively blocks headless scraping —
  scraping it against ToS isn't something I'll build automation for. Removed
  from the run; everything else in your list is included.

Expect to spend ~15–30 minutes on first run fixing selectors for a handful
of `generic` sites. After that it's fully hands-off.

## Project structure

```
job-tracker/
├── config/sites.yaml          # all 50 sites, role/location filters
├── src/
│   ├── main.py                 # orchestrator entry point
│   ├── scraper.py               # Playwright engine + per-ATS strategies
│   ├── filters.py                # role/location relevance logic
│   ├── db.py                      # SQLite storage + hashing
│   ├── diff_engine.py              # NEW/UPDATED/REMOVED detection
│   ├── reports.py                   # HTML + Markdown report generation
│   ├── emailer.py                    # SMTP email sending
│   ├── discover_selectors.py          # selector-tuning helper
│   └── logging_setup.py                # logging config
├── data/job_tracker.db          # SQLite history (created on first run)
├── reports/                      # daily HTML/MD reports
├── logs/                          # daily run logs
├── Dockerfile
├── requirements.txt
├── .env.example
└── .github/workflows/daily-job-tracker.yml
```

## Local setup

```bash
git clone <your-repo-url>
cd job-tracker
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install --with-deps chromium

cp .env.example .env
# edit .env with your SMTP credentials (Gmail App Password recommended)
```

Run once manually:

```bash
python -m src.main
```

This scrapes all active sites, updates `data/job_tracker.db`, writes
`reports/report_<date>.html` and `.md`, and emails you if SMTP env vars are
set (if not set, it just skips email and logs that it did).

## Tuning a `generic` site

If a site's report shows 0 jobs found (check `logs/run_<date>.log`):

```bash
python -m src.discover_selectors <site_id> --headed
```

Example: `python -m src.discover_selectors stripe --headed`

This opens the page, waits for it to render, then prints candidate
repeating link-class selectors ranked by frequency, plus saves a screenshot
and full HTML to `reports/discover_<site_id>.*` so you can inspect the real
DOM. Copy the right selector into `config/sites.yaml`:

```yaml
- id: stripe
  name: "Stripe"
  url: "..."
  ats_type: generic
  job_card_selector: "a.JobsListings__link"   # <- paste what you found
  active: true
```

## Docker

```bash
docker build -t job-tracker .
docker run --rm --env-file .env -v $(pwd)/data:/app/data -v $(pwd)/reports:/app/reports job-tracker
```

## GitHub Actions deployment (daily 11:00 AM IST)

1. Push this repo to GitHub.
2. Go to **Settings → Secrets and variables → Actions** and add:
   - `SMTP_HOST` (e.g. `smtp.gmail.com`)
   - `SMTP_PORT` (e.g. `587`)
   - `SMTP_USER`
   - `SMTP_PASS` (Gmail: use an [App Password](https://myaccount.google.com/apppasswords), not your login password)
   - `EMAIL_TO` (comma-separated if multiple recipients)
3. The workflow at `.github/workflows/daily-job-tracker.yml` runs on cron
   `30 5 * * *` UTC (= 11:00 AM IST, no DST adjustment needed) and can also
   be triggered manually via the "Run workflow" button (**Actions** tab) to
   test before waiting for the schedule.
4. The SQLite DB persists between runs using `actions/cache` keyed on
   `job-tracker-db-*`, so day-over-day diffing works without a separate
   database service. Reports and logs are uploaded as workflow artifacts
   (30-day retention) each run, viewable under the run's **Artifacts**
   section.

## Filters (edit in `config/sites.yaml`)

- `roles.priority_keywords` / `include_keywords` / `exclude_keywords` —
  substring match (case-insensitive) against job titles.
- `locations.preferred_cities` — a job is kept only if its scraped location
  field is empty (unknown — kept by default) or contains one of these
  city/country strings.
- `experience_years` — currently informational; `filters.extract_experience`
  parses "X-Y years" / "X+ years" patterns from the title/description when
  present, but most career sites don't expose structured experience data on
  the listing page, only on the detail page. Extend `RawJob` and the
  relevant `*_strategy` function in `scraper.py` if you want it to open each
  job's detail page to extract this (adds significant runtime across 50
  sites — consider limiting to priority sites only).

## Known limitations

- **Cloudflare-gated sites**: the stealth measures here clear simple JS
  challenges but not interactive CAPTCHAs. Those sites fail with a logged
  error and get retried 3x with backoff; they don't silently return zero
  results as if nothing changed.
- **LinkedIn**: disabled (see above).
- **Michael Page**: this is a recruitment agency aggregator, not a direct
  employer career page — results will include third-party client roles
  under Michael Page's own listing format.
- Sites can change their DOM at any time; if a previously-working `generic`
  site suddenly returns 0 results, re-run `discover_selectors.py` on it.

## Output format

Each report row: Company · Title · Location · Experience (if parsed) ·
Posted date (if the site exposes it) · Direct link · Status (`NEW` /
`UPDATED` / `REMOVED`).

Email subject line: `[Job Tracker] N New Jobs` or
`[Job Tracker] No new openings today`, matching your spec exactly.
