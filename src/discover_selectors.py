"""
Selector discovery helper.

Usage:
    python -m src.discover_selectors <site_id>
    python -m src.discover_selectors <site_id> --headed

For any site using ats_type: generic, this opens the page, waits for it to
settle, then:
  1. Saves a full-page screenshot to reports/discover_<site_id>.png
  2. Saves the rendered HTML to reports/discover_<site_id>.html
  3. Prints candidate repeating-element selectors ranked by frequency, so you
     can quickly identify the real job-card selector and paste it into
     sites.yaml under that site's `job_card_selector` / `title_selector`.

This does NOT try to guess the "correct" selector for you -- career pages
vary too much for that to be reliable. It gives you the raw material to
pick the right one in under a minute instead of viewing page source by hand.
"""
import asyncio
import sys
from collections import Counter
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sites.yaml"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


async def discover(site_id: str, headed: bool):
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    site = next((s for s in cfg["sites"] if s["id"] == site_id), None)
    if not site:
        print(f"No site with id '{site_id}' in sites.yaml")
        sys.exit(1)

    defaults = cfg["defaults"]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        print(f"Loading {site['url']} ...")
        await page.goto(site["url"], timeout=defaults["wait_timeout_ms"], wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state(defaults["wait_strategy"], timeout=defaults["wait_timeout_ms"])
        except Exception:
            print("  (wait_for_load_state timed out, continuing)")
        await page.wait_for_timeout(defaults["extra_wait_ms"] + 1000)

        png_path = REPORTS_DIR / f"discover_{site_id}.png"
        html_path = REPORTS_DIR / f"discover_{site_id}.html"
        await page.screenshot(path=str(png_path), full_page=True)
        html_path.write_text(await page.content(), encoding="utf-8")

        # Report any iframes on the page - if job listings are embedded via
        # an iframe (common for widget-based ATS embeds), normal selectors
        # won't see inside it and sites.yaml needs iframe_selector or
        # iframe_url_contains set instead.
        iframes = await page.query_selector_all("iframe")
        if iframes:
            print(f"\n⚠ Found {len(iframes)} <iframe> element(s) on this page:")
            for idx, ifr in enumerate(iframes):
                src = await ifr.get_attribute("src") or "(no src)"
                ifr_id = await ifr.get_attribute("id") or ""
                ifr_cls = await ifr.get_attribute("class") or ""
                print(f"  [{idx}] src={src}")
                if ifr_id:
                    print(f"       id={ifr_id}  -> could use iframe_selector: \"iframe#{ifr_id}\"")
                if ifr_cls:
                    print(f"       class={ifr_cls}")
                print(f"       -> could use iframe_url_contains: \"{src.split('//')[-1].split('/')[0] if '//' in src else src}\"")
            print("If jobs are inside one of these, add iframe_selector or iframe_url_contains "
                  "to this site's sites.yaml entry instead of job_card_selector alone.\n")

        # Find anchor tags whose href looks like a job link, grouped by class signature
        anchors = await page.eval_on_selector_all(
            "a",
            """els => els.map(e => ({
                href: e.getAttribute('href') || '',
                cls: e.className || '',
                text: (e.innerText || '').trim().slice(0, 80)
            }))""",
        )
        job_like = [a for a in anchors if any(k in (a["href"] or "").lower() for k in
                    ["job", "career", "position", "opening", "req", "vacan"])]

        class_counter = Counter(a["cls"] for a in job_like if a["cls"])
        print(f"\nFound {len(job_like)} job-like anchors out of {len(anchors)} total <a> tags.")
        print("\nTop repeated class signatures on job-like links (candidate selectors):")
        for cls, count in class_counter.most_common(10):
            print(f"  [{count}x] a.{cls.replace(' ', '.')}")

        print("\nSample job-like links:")
        for a in job_like[:8]:
            print(f"  - {a['text'][:60]!r} -> {a['href']}")

        print(f"\nScreenshot saved: {png_path}")
        print(f"Full HTML saved:  {html_path}")
        print(f"\nOnce you've identified the right selector, edit config/sites.yaml:")
        print(f"  - id: {site_id}\n    job_card_selector: \"<your selector here>\"")

        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.discover_selectors <site_id> [--headed]")
        sys.exit(1)
    site_id = sys.argv[1]
    headed = "--headed" in sys.argv
    asyncio.run(discover(site_id, headed))
