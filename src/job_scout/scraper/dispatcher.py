import asyncio
import logging
import random
import re

import httpx
from bs4 import BeautifulSoup

from job_scout.models import SiteTarget
from job_scout.scraper.http_scraper import fetch_html
from job_scout.scraper.playwright_scraper import fetch_html_with_browser

logger = logging.getLogger(__name__)

_REMOVE_TAGS = ["script", "style", "nav", "footer", "header"]


class ScrapingFailedError(Exception):
    """Raised when all applicable scraping tiers fail for a site."""


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


async def fetch_site_content(
    target: SiteTarget,
    http_client: httpx.AsyncClient,
) -> tuple[str, str]:
    """Return (cleaned_text, tier_used). Raises ScrapingFailedError if all tiers fail."""
    if target.scrape_tier == "http":
        html = await fetch_html(target.url, http_client)
        if html is not None:
            return _clean_html(html), "http"
        logger.info("HTTP failed for %s, falling back to Playwright", target.name)
        await asyncio.sleep(random.uniform(1, 3))

    html = await fetch_html_with_browser(target.url)
    if html is not None:
        return _clean_html(html), "playwright"

    raise ScrapingFailedError(
        f"All scraping tiers failed for {target.name} ({target.url})"
    )
