"""
Test the REAL scraper (same strategies main.py uses) against just the
sites you name, without touching the database, reports, or email.

Usage:
    python -m src.test_sites vinfast skyroot
    python -m src.test_sites vinfast skyroot --headed
"""
import asyncio
import sys
from pathlib import Path

import yaml

from src.scraper import scrape_all

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sites.yaml"


async def main(site_ids: list[str]):
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    defaults = cfg["defaults"]
    sites = [s for s in cfg["sites"] if s["id"] in site_ids]

    missing = set(site_ids) - {s["id"] for s in sites}
    if missing:
        print(f"Unknown site ids: {missing}")

    if not sites:
        print("Nothing to test.")
        return

    results = await scrape_all(sites, defaults, concurrency=len(sites))

    print("\n" + "=" * 70)
    for r in results:
        print(f"\n{r.site_id}: success={r.success}, jobs_found={len(r.jobs)}")
        if r.error:
            print(f"  error: {r.error}")
        for j in r.jobs[:8]:
            print(f"  - {j.title!r} -> {j.link}")
        if len(r.jobs) > 8:
            print(f"  ... and {len(r.jobs) - 8} more")
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.test_sites <site_id> [<site_id> ...]")
        sys.exit(1)
    ids = [a for a in sys.argv[1:] if a != "--headed"]
    asyncio.run(main(ids))