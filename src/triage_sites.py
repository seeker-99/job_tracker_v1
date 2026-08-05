"""
Batch triage for sites that returned 0 postings (or failed) in a run.

Usage:
    python -m src.triage_sites                       # triage all active sites
    python -m src.triage_sites rtx mastercard gartner # triage just these site_ids
    python -m src.triage_sites --headed rtx           # watch it happen in a browser

What it does, per site:
  1. Loads the page the same way the real scraper does.
  2. Takes a screenshot -> reports/triage_<site_id>.png
  3. Scans the rendered page text for bot-block / CAPTCHA markers.
  4. Scans for "no results" phrasing.
  5. Prints a verdict: BLOCKED (captcha/bot-check) | EMPTY (page loaded, genuinely
     no matching jobs) | LIKELY_SELECTOR_ISSUE (page has content but our
     selector found nothing) | ERROR (page failed to load at all).

This does not try to bypass or solve CAPTCHAs. It only tells you which
bucket each site falls into so you know whether to: fix a selector, mark
the site `active: false`, or just leave it (transient empty result).
"""
import asyncio
import sys
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sites.yaml"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

CAPTCHA_MARKERS = [
    "captcha", "recaptcha", "hcaptcha", "verify you are human",
    "checking your browser", "cf-challenge", "just a moment",
    "access denied", "are you a robot", "unusual traffic",
    "bot detection", "security check",
]

EMPTY_MARKERS = [
    "no jobs found", "no matching", "no results", "no positions",
    "0 results", "no openings", "no roles found", "try adjusting your search",
]


async def triage_one(pw, site: dict, defaults: dict, headed: bool) -> dict:
    browser = await pw.chromium.launch(headless=not headed)
    page = await browser.new_page(
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    result = {"site_id": site["id"], "name": site["name"], "verdict": "ERROR", "detail": ""}
    try:
        await page.goto(site["url"], timeout=defaults["wait_timeout_ms"], wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state(defaults["wait_strategy"], timeout=defaults["wait_timeout_ms"])
        except Exception:
            pass
        await page.wait_for_timeout(defaults["extra_wait_ms"] + 1500)

        png_path = REPORTS_DIR / f"triage_{site['id']}.png"
        await page.screenshot(path=str(png_path), full_page=True)

        body_text = (await page.inner_text("body")).lower()
        total_links = len(await page.query_selector_all("a"))

        if any(m in body_text for m in CAPTCHA_MARKERS):
            result["verdict"] = "BLOCKED"
            result["detail"] = "CAPTCHA / bot-check text found on page"
        elif any(m in body_text for m in EMPTY_MARKERS):
            result["verdict"] = "EMPTY"
            result["detail"] = "Page explicitly says no results"
        elif total_links < 15:
            result["verdict"] = "ERROR"
            result["detail"] = f"Page rendered almost no content ({total_links} links) - may need longer wait or is broken"
        else:
            result["verdict"] = "LIKELY_SELECTOR_ISSUE"
            result["detail"] = f"Page has real content ({total_links} links) but our selector matched 0 - screenshot it and pick a better selector"

        result["screenshot"] = str(png_path)
    except Exception as e:
        result["verdict"] = "ERROR"
        result["detail"] = str(e)
    finally:
        await browser.close()
    return result


async def main(site_ids: list[str], headed: bool):
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    defaults = cfg["defaults"]
    sites = cfg["sites"]

    if site_ids:
        targets = [s for s in sites if s["id"] in site_ids]
        missing = set(site_ids) - {s["id"] for s in targets}
        if missing:
            print(f"Unknown site ids (skipped): {missing}")
    else:
        targets = [s for s in sites if s.get("active", True)]

    print(f"Triaging {len(targets)} site(s)...\n")

    results = []
    async with async_playwright() as pw:
        for site in targets:
            print(f"  checking {site['id']} ...", end=" ", flush=True)
            r = await triage_one(pw, site, defaults, headed)
            print(r["verdict"])
            results.append(r)

    print("\n" + "=" * 90)
    print(f"{'SITE':<25} {'VERDICT':<24} DETAIL")
    print("=" * 90)
    for r in results:
        print(f"{r['site_id']:<25} {r['verdict']:<24} {r['detail']}")
    print("=" * 90)

    blocked = [r["site_id"] for r in results if r["verdict"] == "BLOCKED"]
    selector_issue = [r["site_id"] for r in results if r["verdict"] == "LIKELY_SELECTOR_ISSUE"]
    empty = [r["site_id"] for r in results if r["verdict"] == "EMPTY"]
    errored = [r["site_id"] for r in results if r["verdict"] == "ERROR"]

    print(f"\nBLOCKED ({len(blocked)}) -> consider setting active: false in sites.yaml: {blocked}")
    print(f"LIKELY_SELECTOR_ISSUE ({len(selector_issue)}) -> run discover_selectors on these: {selector_issue}")
    print(f"EMPTY ({len(empty)}) -> nothing to fix, genuinely no matches right now: {empty}")
    print(f"ERROR ({len(errored)}) -> investigate individually: {errored}")
    print(f"\nScreenshots saved to reports/triage_<site_id>.png for all of the above.")


if __name__ == "__main__":
    args = sys.argv[1:]
    headed = "--headed" in args
    site_ids = [a for a in args if a != "--headed"]
    asyncio.run(main(site_ids, headed))
