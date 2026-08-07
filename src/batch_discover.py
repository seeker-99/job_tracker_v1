"""
Batch selector discovery - runs discover_selectors logic on multiple sites
concurrently and writes ONE combined summary file, so you can paste the
whole thing back in a single message instead of running sites one at a time.

Usage:
    python -m src.batch_discover mastercard stryker skyroot rtx_oracle_aerospace oracle_hcm_2 skoda_vw pi_website ather_energy caterpillar gm hrone greyorange greenhouse_india_all

    # or with no args, discovers every site currently returning 0 jobs
    # according to the most recent run log (auto-detected)
    python -m src.batch_discover

Output: reports/batch_discover_summary.txt (paste this whole file back)
Also saves individual screenshots: reports/discover_<site_id>.png
"""
import asyncio
import re
import sys
from collections import Counter
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sites.yaml"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
REPORTS_DIR.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def find_zero_result_sites() -> list[str]:
    """Scan the most recent log file for '-> 0 raw postings found on X' lines."""
    logs = sorted(LOGS_DIR.glob("run_*.log"))
    if not logs:
        return []
    latest = logs[-1]
    text = latest.read_text(encoding="utf-8", errors="ignore")
    return re.findall(r"-> 0 raw postings found on (\S+)", text)


async def discover_one(pw, site: dict, defaults: dict, sem: asyncio.Semaphore) -> str:
    async with sem:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900}, user_agent=USER_AGENT)
        lines = [f"\n{'='*90}\nSITE: {site['id']}  ({site['name']})\nURL: {site['url']}\n{'='*90}"]
        try:
            await page.goto(site["url"], timeout=defaults["wait_timeout_ms"], wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state(defaults["wait_strategy"], timeout=defaults["wait_timeout_ms"])
            except Exception:
                lines.append("(wait_for_load_state timed out, continued anyway)")
            await page.wait_for_timeout(defaults["extra_wait_ms"] + 1500)

            png_path = REPORTS_DIR / f"discover_{site['id']}.png"
            await page.screenshot(path=str(png_path), full_page=True)

            anchors = await page.eval_on_selector_all(
                "a",
                """els => els.map(e => ({
                    href: e.getAttribute('href') || '',
                    cls: e.className || '',
                    text: (e.innerText || '').trim().slice(0, 80),
                    aria: e.getAttribute('aria-label') || ''
                }))""",
            )
            job_like = [a for a in anchors if any(k in (a["href"] or "").lower() for k in
                        ["job", "career", "position", "opening", "req", "vacan"])]

            body_text = (await page.inner_text("body")).lower()
            captcha_markers = ["captcha", "recaptcha", "verify you are human", "access denied",
                                "checking your browser", "just a moment", "unusual traffic"]
            is_blocked = any(m in body_text for m in captcha_markers)

            lines.append(f"Total <a> tags: {len(anchors)} | Job-like anchors: {len(job_like)} | Screenshot: {png_path.name}")
            if is_blocked:
                lines.append("!! POSSIBLE CAPTCHA / BOT-BLOCK detected on this page !!")

            class_counter = Counter(a["cls"] for a in job_like if a["cls"])
            lines.append("\nTop candidate class signatures:")
            for cls, count in class_counter.most_common(6):
                lines.append(f"  [{count}x] a.{cls.replace(' ', '.')}")

            lines.append("\nSample job-like links (title -> href [aria-label if present]):")
            for a in job_like[:10]:
                aria = f"  [aria-label: {a['aria'][:60]}]" if a["aria"] else ""
                lines.append(f"  - {a['text'][:60]!r} -> {a['href']}{aria}")

            if not job_like:
                lines.append("  (none found - page may be a landing page, iframe-embedded widget, or needs a different URL)")

        except Exception as e:
            lines.append(f"ERROR loading page: {e}")
        finally:
            await browser.close()
        return "\n".join(lines)


async def main(site_ids: list[str]):
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    defaults = cfg["defaults"]
    all_sites = {s["id"]: s for s in cfg["sites"]}

    if not site_ids:
        site_ids = find_zero_result_sites()
        if not site_ids:
            print("No site ids given and no zero-result sites found in latest log. "
                  "Usage: python -m src.batch_discover <id1> <id2> ...")
            return
        print(f"Auto-detected {len(site_ids)} zero-result sites from latest log: {site_ids}\n")

    targets = [all_sites[sid] for sid in site_ids if sid in all_sites]
    missing = set(site_ids) - {s["id"] for s in targets}
    if missing:
        print(f"Unknown site ids (skipped): {missing}")

    print(f"Discovering {len(targets)} sites (4 at a time)...")

    sections = []
    async with async_playwright() as pw:
        sem = asyncio.Semaphore(4)
        results = await asyncio.gather(*(discover_one(pw, s, defaults, sem) for s in targets))
        sections.extend(results)

    out_path = REPORTS_DIR / "batch_discover_summary.txt"
    out_path.write_text("\n".join(sections), encoding="utf-8")

    print(f"\nDone. Combined summary written to: {out_path}")
    print("Open that file, copy ALL of it, and paste it back in one message.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))