"""
SQLite persistence layer.

Schema:
  jobs(
    job_key TEXT PRIMARY KEY,   -- stable identity: site_id + normalized link
    site_id TEXT,
    company TEXT,
    title TEXT,
    location TEXT,
    experience TEXT,
    posted_date TEXT,
    link TEXT,
    content_hash TEXT,          -- hash of (title, location, experience, posted_date)
    first_seen_run TEXT,
    last_seen_run TEXT,
    status TEXT                 -- 'active' | 'removed'
  )

  runs(
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    sites_scraped INTEGER,
    sites_failed INTEGER,
    new_count INTEGER,
    updated_count INTEGER,
    removed_count INTEGER
  )
"""
import sqlite3
import hashlib
import contextlib
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "job_tracker.db"
DB_PATH.parent.mkdir(exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_key TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    company TEXT,
    title TEXT,
    location TEXT,
    experience TEXT,
    posted_date TEXT,
    link TEXT,
    content_hash TEXT,
    first_seen_run TEXT,
    last_seen_run TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    sites_scraped INTEGER,
    sites_failed INTEGER,
    new_count INTEGER,
    updated_count INTEGER,
    removed_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jobs_site ON jobs(site_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def make_job_key(site_id: str, link: str) -> str:
    normalized = (link or "").strip().split("?")[0].rstrip("/")
    return hashlib.sha256(f"{site_id}::{normalized}".encode()).hexdigest()[:24]


def content_hash(title: str, location: str, experience: str, posted_date: str) -> str:
    raw = "|".join([title or "", location or "", experience or "", posted_date or ""])
    return hashlib.sha256(raw.encode()).hexdigest()


@contextlib.contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def start_run(run_id: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at, sites_scraped, sites_failed, "
            "new_count, updated_count, removed_count) VALUES (?, ?, 0, 0, 0, 0, 0)",
            (run_id, datetime.now(timezone.utc).isoformat()),
        )


def finish_run(run_id: str, sites_scraped: int, sites_failed: int,
                new_count: int, updated_count: int, removed_count: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, sites_scraped=?, sites_failed=?, "
            "new_count=?, updated_count=?, removed_count=? WHERE run_id=?",
            (datetime.now(timezone.utc).isoformat(), sites_scraped, sites_failed,
             new_count, updated_count, removed_count, run_id),
        )


def get_existing_jobs_for_site(site_id: str) -> dict:
    """Returns {job_key: row_dict} for all currently-active jobs at a site."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE site_id=? AND status='active'", (site_id,)
        ).fetchall()
        return {r["job_key"]: dict(r) for r in rows}


def upsert_job(job_key: str, site_id: str, company: str, title: str, location: str,
                experience: str, posted_date: str, link: str, chash: str, run_id: str):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT job_key FROM jobs WHERE job_key=?", (job_key,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE jobs SET company=?, title=?, location=?, experience=?, "
                "posted_date=?, link=?, content_hash=?, last_seen_run=?, status='active' "
                "WHERE job_key=?",
                (company, title, location, experience, posted_date, link, chash, run_id, job_key),
            )
        else:
            conn.execute(
                "INSERT INTO jobs (job_key, site_id, company, title, location, experience, "
                "posted_date, link, content_hash, first_seen_run, last_seen_run, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')",
                (job_key, site_id, company, title, location, experience, posted_date,
                 link, chash, run_id, run_id),
            )


def mark_removed(job_keys: list[str], run_id: str):
    if not job_keys:
        return
    with get_conn() as conn:
        conn.executemany(
            "UPDATE jobs SET status='removed', last_seen_run=? WHERE job_key=?",
            [(run_id, k) for k in job_keys],
        )
