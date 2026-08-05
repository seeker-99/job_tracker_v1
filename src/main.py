"""
Entry point. Run with:  python -m src.main
Runs the full pipeline: scrape all active sites -> diff vs SQLite -> reports -> email.
"""
import asyncio
import sys
import uuid
import yaml
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from src import db
from src.scraper import scrape_all
from src.diff_engine import diff_site
from src.reports import generate_html, generate_markdown
from src.emailer import send_email
from src.logging_setup import get_logger

load_dotenv()
logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sites.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def run():
    cfg = load_config()
    defaults = cfg["defaults"]
    roles_cfg = cfg["roles"]
    locations_cfg = cfg["locations"]
    sites = [s for s in cfg["sites"]]

    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    date_str = datetime.now().strftime("%Y-%m-%d")
    db.start_run(run_id)

    active_sites = [s for s in sites if s.get("active", True)]
    logger.info("Starting run %s: %d active sites of %d total", run_id, len(active_sites), len(sites))

    results = await scrape_all(sites, defaults, concurrency=4)

    all_diffs = []
    failed_sites = []
    scraped_ok = 0

    for site, result in zip(sites, results):
        if not site.get("active", True):
            continue
        if not result.success:
            failed_sites.append(f"{site['name']} ({site['id']}): {result.error}")
            continue
        scraped_ok += 1
        diffs = diff_site(site["id"], site["name"], result.jobs, roles_cfg, locations_cfg, run_id)
        all_diffs.extend(diffs)
        if diffs:
            logger.info("%s: %d relevant changes", site["name"], len(diffs))

    new_count = sum(1 for d in all_diffs if d.status == "NEW")
    updated_count = sum(1 for d in all_diffs if d.status == "UPDATED")
    removed_count = sum(1 for d in all_diffs if d.status == "REMOVED")

    db.finish_run(run_id, scraped_ok, len(failed_sites), new_count, updated_count, removed_count)

    html_path = generate_html(all_diffs, failed_sites, date_str)
    md_path = generate_markdown(all_diffs, failed_sites, date_str)
    logger.info("Reports written: %s , %s", html_path, md_path)

    total_changes = new_count + updated_count
    if total_changes > 0:
        subject = f"[Job Tracker] {total_changes} New Job{'s' if total_changes != 1 else ''}"
    else:
        subject = "[Job Tracker] No new openings today"

    html_body = Path(html_path).read_text(encoding="utf-8")

    if __send_email_enabled():
        try:
            send_email(subject, html_body, md_path)
        except Exception:
            logger.error("Email sending failed; reports are still available in ./reports")
    else:
        logger.info("Email sending disabled (SMTP env vars not set). Skipping.")

    logger.info(
        "Run complete: %d new, %d updated, %d removed, %d sites failed",
        new_count, updated_count, removed_count, len(failed_sites),
    )
    if failed_sites:
        logger.warning("Failed sites: %s", failed_sites)

    return 0


def __send_email_enabled() -> bool:
    import os
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "EMAIL_TO"))


def main():
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
