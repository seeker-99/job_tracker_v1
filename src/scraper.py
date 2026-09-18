"""
Playwright-based scraping engine.

Design notes (read this before extending):
- One Chromium browser instance is launched and reused for the whole run
  ("browser reuse"); each site gets its own fresh context (cookies isolated)
  but pages are opened/closed per site to bound memory.
- Every site goes through a `strategy` function chosen by `ats_type`.
  Known ATS platforms (Greenhouse, Workday, Oracle Cloud HCM, Zoho Recruit,
  Darwinbox, Avature) get platform-aware extraction because their DOM
  structure is predictable across tenants. Anything else falls back to
  `generic_strategy`, which uses the CSS selectors from sites.yaml
  (defaults + per-site overrides). Those generic selectors are BEST-GUESS
  DEFAULTS -- verify/tune them with `python -m src.discover_selectors <id>`
  before trusting results from a `generic` site.
- Cloudflare / bot-challenge tolerance: we set a realistic user agent,
  disable the `navigator.webdriver` flag via playwright-stealth, and wait
  on `networkidle` with an extra settle delay. This clears simple
  JS-challenge pages but will NOT solve interactive CAPTCHAs -- those sites
  will fail cleanly and get logged + retried, not silently skipped.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, unquote_plus

from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PWTimeout
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.logging_setup import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class RawJob:
    title: str
    link: str
    location: str = ""
    posted_date: str = ""
    experience: str = ""


@dataclass
class SiteResult:
    site_id: str
    success: bool
    jobs: list = field(default_factory=list)
    error: Optional[str] = None


async def new_context(pw_browser) -> BrowserContext:
    ctx = await pw_browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="en-IN",
    )
    await ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return ctx


async def _settle(page: Page, wait_strategy: str, timeout_ms: int, extra_wait_ms: int):
    try:
        await page.wait_for_load_state(wait_strategy, timeout=timeout_ms)
    except PWTimeout:
        logger.warning("wait_for_load_state(%s) timed out, continuing anyway", wait_strategy)
    await page.wait_for_timeout(extra_wait_ms)


_TITLE_FALLBACK_SELECTORS = [
    "h1", "h2", "h3", "h4", "h5",
    "[class*='title' i]", "[class*='job-name' i]", "[class*='position' i]",
    "strong", "b",
]

MAX_TITLE_LEN = 140


def _clean_title(raw: str) -> str:
    collapsed = " ".join(raw.split())
    first_line = raw.split("\n")[0].strip()
    candidate = first_line if 0 < len(first_line) < len(collapsed) else collapsed
    if len(candidate) > MAX_TITLE_LEN:
        candidate = candidate[:MAX_TITLE_LEN].rsplit(" ", 1)[0] + "…"
    return candidate.strip()


async def _get_scrape_target(page: Page, site: dict):
    iframe_sel = site.get("iframe_selector")
    iframe_url_contains = site.get("iframe_url_contains")

    if iframe_sel:
        try:
            await page.wait_for_selector(iframe_sel, timeout=10000)
        except PWTimeout:
            logger.warning("iframe_selector '%s' never appeared on %s", iframe_sel, site["id"])
        el = await page.query_selector(iframe_sel)
        if el:
            frame = await el.content_frame()
            if frame:
                return frame

    if iframe_url_contains:
        for f in page.frames:
            if iframe_url_contains in (f.url or ""):
                return f

    return page


async def generic_strategy(page: Page, site: dict, defaults: dict) -> list[RawJob]:
    card_sel = site.get("job_card_selector") or defaults["job_card_selector"]
    title_sel = site.get("title_selector") or defaults.get("title_selector")
    location_sel = site.get("location_selector") or defaults.get("location_selector")
    posted_date_sel = site.get("posted_date_selector")
    title_attr = site.get("title_attr")
    title_attr_strip_prefix = site.get("title_attr_strip_prefix", "")
    # Some sites (e.g. torqueagi) put the title in a URL query parameter
    # instead of visible text or an attribute - e.g. href="...?position=Job%20Title".
    title_url_param = site.get("title_url_param")  # e.g. "position"

    target = await _get_scrape_target(page, site)
    base_url = getattr(target, "url", page.url)

    cards = await target.query_selector_all(card_sel)
    jobs = []
    seen_links = set()
    for card in cards:
        href = await card.get_attribute("href")
        if not href:
            inner = await card.query_selector("a")
            href = await inner.get_attribute("href") if inner else None
        if not href:
            continue
        link = urljoin(base_url, href)
        if link in seen_links:
            continue
        seen_links.add(link)

        title = ""
        if title_url_param:
            qs = parse_qs(urlparse(link).query)
            values = qs.get(title_url_param)
            if values:
                title = unquote_plus(values[0]).strip()

        if not title and title_attr:
            raw_attr = (await card.get_attribute(title_attr)) or ""
            if title_attr_strip_prefix and raw_attr.startswith(title_attr_strip_prefix):
                raw_attr = raw_attr[len(title_attr_strip_prefix):]
            title = raw_attr.strip()

        if not title and title_sel:
            title_el = await card.query_selector(title_sel)
            if title_el:
                title = (await title_el.inner_text()).strip()

        if not title:
            for fallback_sel in _TITLE_FALLBACK_SELECTORS:
                el = await card.query_selector(fallback_sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        title = text
                        break

        if not title:
            title = (await card.inner_text()).strip()

        title = _clean_title(title)

        location = ""
        if location_sel:
            loc_el = await card.query_selector(location_sel)
            if loc_el:
                location = (await loc_el.inner_text()).strip()

        posted_date = ""
        if posted_date_sel:
            date_el = await card.query_selector(posted_date_sel)
            if date_el:
                posted_date = (await date_el.inner_text()).strip()

        if title:
            jobs.append(RawJob(title=title, link=link, location=location, posted_date=posted_date))
    return jobs


async def greenhouse_strategy(page: Page, site: dict, defaults: dict) -> list[RawJob]:
    rows = await page.query_selector_all("tr.job, div.opening, a[href*='/jobs/']")
    jobs, seen = [], set()
    for row in rows:
        href = await row.get_attribute("href")
        if not href:
            link_el = await row.query_selector("a")
            href = await link_el.get_attribute("href") if link_el else None
        if not href:
            continue
        link = urljoin(page.url, href)
        if link in seen:
            continue
        seen.add(link)
        text = (await row.inner_text()).strip()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = lines[0] if lines else ""
        location = lines[1] if len(lines) > 1 else ""
        if title:
            jobs.append(RawJob(title=title, link=link, location=location))
    return jobs


async def workday_strategy(page: Page, site: dict, defaults: dict) -> list[RawJob]:
    els = await page.query_selector_all("a[data-automation-id='jobTitle']")
    jobs = []
    for el in els:
        href = await el.get_attribute("href")
        title = (await el.inner_text()).strip()
        if not href or not title:
            continue
        link = urljoin(page.url, href)
        location = ""
        try:
            container = await el.evaluate_handle(
                "node => node.closest('li') || node.closest('[data-automation-id=\"jobItem\"]')"
            )
            if container:
                loc_el = await container.as_element().query_selector(
                    "[data-automation-id='subtitle'], [data-automation-id='locations']"
                )
                if loc_el:
                    location = (await loc_el.inner_text()).strip()
        except Exception:
            pass
        jobs.append(RawJob(title=title, link=link, location=location))
    return jobs


async def oracle_cloud_hcm_strategy(page: Page, site: dict, defaults: dict) -> list[RawJob]:
    els = await page.query_selector_all("a[href*='/job/'], li.job-tile a, div.job-tile a")
    jobs, seen = [], set()
    for el in els:
        href = await el.get_attribute("href")
        title = (await el.inner_text()).strip()
        if not href or not title or href in seen:
            continue
        seen.add(href)
        jobs.append(RawJob(title=title.split("\n")[0], link=urljoin(page.url, href)))
    return jobs


async def zoho_recruit_strategy(page: Page, site: dict, defaults: dict) -> list[RawJob]:
    els = await page.query_selector_all(
        "a.cw-3-title.cw-bw, a.cw-1-title, a.job-title, div.jobLists a, table a"
    )
    jobs, seen = [], set()
    for el in els:
        href = await el.get_attribute("href")
        title = (await el.inner_text()).strip()
        if not href or not title or href in seen:
            continue
        if title.upper() == "LOGIN" or "candidateportal" in href:
            continue
        seen.add(href)
        jobs.append(RawJob(title=title, link=urljoin(page.url, href)))
    return jobs


async def darwinbox_strategy(page: Page, site: dict, defaults: dict) -> list[RawJob]:
    els = await page.query_selector_all("div.job-card a, li.job-item a, a[href*='job']")
    jobs, seen = [], set()
    for el in els:
        href = await el.get_attribute("href")
        title = (await el.inner_text()).strip()
        if not href or not title or href in seen:
            continue
        seen.add(href)
        jobs.append(RawJob(title=title.split("\n")[0], link=urljoin(page.url, href)))
    return jobs


async def avature_strategy(page: Page, site: dict, defaults: dict) -> list[RawJob]:
    els = await page.query_selector_all("a.job-title-link, div.jobResult a, a[href*='JobDetail']")
    jobs, seen = [], set()
    for el in els:
        href = await el.get_attribute("href")
        title = (await el.inner_text()).strip()
        if not href or not title or href in seen:
            continue
        seen.add(href)
        jobs.append(RawJob(title=title, link=urljoin(page.url, href)))
    return jobs


async def mokahr_strategy(page: Page, site: dict, defaults: dict) -> list[RawJob]:
    els = await page.query_selector_all("div[class*='job-item'] a, li[class*='job'] a, a[href*='position']")
    jobs, seen = [], set()
    for el in els:
        href = await el.get_attribute("href")
        title = (await el.inner_text()).strip()
        if not href or not title or href in seen:
            continue
        seen.add(href)
        jobs.append(RawJob(title=title.split("\n")[0], link=urljoin(page.url, href)))
    return jobs


STRATEGIES = {
    "generic": generic_strategy,
    "greenhouse": greenhouse_strategy,
    "workday": workday_strategy,
    "oracle_cloud_hcm": oracle_cloud_hcm_strategy,
    "zoho_recruit": zoho_recruit_strategy,
    "darwinbox": darwinbox_strategy,
    "avature": avature_strategy,
    "mokahr": mokahr_strategy,
    "linkedin": None,
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((PWTimeout, Exception)),
    reraise=True,
)
async def _load_and_extract(context: BrowserContext, site: dict, defaults: dict) -> list[RawJob]:
    page = await context.new_page()
    try:
        await page.goto(site["url"], timeout=defaults["wait_timeout_ms"], wait_until="domcontentloaded")
        await _settle(
            page,
            site.get("wait_strategy", defaults["wait_strategy"]),
            defaults["wait_timeout_ms"],
            site.get("extra_wait_ms", defaults["extra_wait_ms"]),
        )
        strategy = STRATEGIES.get(site["ats_type"])
        if strategy is None:
            raise RuntimeError(f"ats_type '{site['ats_type']}' has no scraping strategy (see sites.yaml notes)")
        jobs = await strategy(page, site, defaults)
        return jobs
    finally:
        await page.close()


async def scrape_site(pw_browser, site: dict, defaults: dict) -> SiteResult:
    if not site.get("active", True):
        logger.info("Skipping inactive site: %s", site["id"])
        return SiteResult(site_id=site["id"], success=True, jobs=[])

    logger.info("Scraping %s (%s)", site["name"], site["url"])
    context = await new_context(pw_browser)
    try:
        jobs = await _load_and_extract(context, site, defaults)
        logger.info("  -> %d raw postings found on %s", len(jobs), site["id"])
        return SiteResult(site_id=site["id"], success=True, jobs=jobs)
    except Exception as e:
        logger.error("  -> FAILED %s: %s", site["id"], e)
        return SiteResult(site_id=site["id"], success=False, error=str(e))
    finally:
        await context.close()


async def scrape_all(sites: list[dict], defaults: dict, concurrency: int = 4) -> list[SiteResult]:
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        sem = asyncio.Semaphore(concurrency)

        async def bound_scrape(site):
            async with sem:
                return await scrape_site(browser, site, defaults)

        results = await asyncio.gather(*(bound_scrape(s) for s in sites))
        await browser.close()
    return list(results)
