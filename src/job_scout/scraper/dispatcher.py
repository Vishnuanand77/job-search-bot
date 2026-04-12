import json
import logging
import re

from playwright.async_api import BrowserContext
from bs4 import BeautifulSoup

from job_scout.models import SiteTarget
from job_scout.scraper.playwright_scraper import (
    fetch_html_with_browser,
    fetch_html_with_context,
)

logger = logging.getLogger(__name__)

_REMOVE_TAGS = ["script", "style", "nav", "footer", "header"]


class ScrapingFailedError(Exception):
    """Raised when all applicable scraping tiers fail for a site."""


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Extract datePosted from JSON-LD before script tags are removed.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        date_posted = data.get("datePosted")
        if date_posted:
            script.replace_with(f"datePosted: {date_posted}")

    # Normalize <time datetime="..."> — replace display text with the ISO value.
    for time_tag in soup.find_all("time", datetime=True):
        time_tag.string = time_tag["datetime"]

    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


async def fetch_site_content(
    target: SiteTarget,
    context: BrowserContext | None = None,
) -> tuple[str, str]:
    """Return (cleaned_text, tier_used). Raises ScrapingFailedError if scraping fails.

    If context is provided, reuses it. Otherwise creates a new browser.
    """
    if context is not None:
        html = await fetch_html_with_context(target.url, context)
    else:
        html = await fetch_html_with_browser(target.url)

    if html is not None:
        return _clean_html(html), "playwright"

    raise ScrapingFailedError(
        f"Scraping failed for {target.name} ({target.url})"
    )
