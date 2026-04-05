import logging

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from job_scout.scraper.http_scraper import BROWSER_HEADERS

logger = logging.getLogger(__name__)

NETWORKIDLE_TIMEOUT = 15_000  # ms


async def fetch_html_with_browser(url: str) -> str | None:
    """Fetch page HTML using headless Chromium. Always cleans up the browser."""
    try:
        async with async_playwright() as pw:
            async with await pw.chromium.launch(headless=True) as browser:
                context = await browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"]
                )
                page = await context.new_page()
                await page.goto(url)
                await page.wait_for_load_state(
                    "networkidle", timeout=NETWORKIDLE_TIMEOUT
                )
                return await page.content()
    except PlaywrightTimeoutError:
        logger.warning("Playwright timeout waiting for networkidle: %s", url)
        return None
    except Exception as exc:
        logger.warning("Playwright error fetching %s: %s", url, exc)
        return None
