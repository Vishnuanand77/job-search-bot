import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}

SCRAPE_TIMEOUT = 30.0


async def fetch_html(url: str, client: httpx.AsyncClient) -> str | None:
    """Fetch raw HTML via HTTP. Returns None on 403, timeout, or connection error.

    Re-raises HTTPStatusError for 429 (rate limit) so that @_retry can handle it.
    """
    try:
        response = await client.get(url, headers=BROWSER_HEADERS, timeout=SCRAPE_TIMEOUT)
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as exc:
        # For 429 (Too Many Requests), respect Retry-After and re-raise so @_retry handles it
        if exc.response.status_code == 429:
            retry_after = exc.response.headers.get("Retry-After", "60")
            try:
                wait_seconds = int(retry_after)
            except ValueError:
                # Retry-After can be an HTTP-date; default to 60s in that case
                wait_seconds = 60
            logger.warning("HTTP 429 fetching %s; waiting %d seconds before retry", url, wait_seconds)
            # Re-raise so @_retry decorator can handle the retry with proper backoff
            raise

        # For other 4xx/5xx errors, log and return None (no retry)
        logger.warning("HTTP %s fetching %s", exc.response.status_code, url)
        return None
    except httpx.TimeoutException:
        logger.warning("Timeout fetching %s", url)
        return None
    except httpx.ConnectError:
        logger.warning("Connection error fetching %s", url)
        return None
