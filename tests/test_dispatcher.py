import httpx
import pytest
import respx
from unittest.mock import AsyncMock, patch

from job_scout.models import SiteTarget
from job_scout.scraper.dispatcher import ScrapingFailedError, fetch_site_content


def make_http_target() -> SiteTarget:
    return SiteTarget(name="Test Corp", url="https://example.com/careers", scrape_tier="http")


def make_playwright_target() -> SiteTarget:
    return SiteTarget(name="Startup Co", url="https://startup.io/jobs", scrape_tier="playwright")


@pytest.mark.asyncio
async def test_returns_http_content_when_http_succeeds():
    html = "<html><body><p>Engineer role</p></body></html>"
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(200, text=html)
        )
        async with httpx.AsyncClient() as client:
            text, tier = await fetch_site_content(make_http_target(), client)

    assert "Engineer role" in text
    assert tier == "http"


@pytest.mark.asyncio
async def test_falls_back_to_playwright_when_http_returns_none():
    playwright_html = "<html><body><p>Playwright job</p></body></html>"
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(403)
        )
        with patch(
            "job_scout.scraper.dispatcher.fetch_html_with_browser",
            new=AsyncMock(return_value=playwright_html),
        ):
            async with httpx.AsyncClient() as client:
                text, tier = await fetch_site_content(make_http_target(), client)

    assert "Playwright job" in text
    assert tier == "playwright"


@pytest.mark.asyncio
async def test_raises_scraping_failed_when_both_tiers_fail():
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(403)
        )
        with patch(
            "job_scout.scraper.dispatcher.fetch_html_with_browser",
            new=AsyncMock(return_value=None),
        ):
            async with httpx.AsyncClient() as client:
                with pytest.raises(ScrapingFailedError):
                    await fetch_site_content(make_http_target(), client)


@pytest.mark.asyncio
async def test_playwright_tier_does_not_attempt_http():
    playwright_html = "<html><body><p>JS job</p></body></html>"
    with patch(
        "job_scout.scraper.dispatcher.fetch_html_with_browser",
        new=AsyncMock(return_value=playwright_html),
    ) as mock_pw, patch(
        "job_scout.scraper.dispatcher.fetch_html",
        new=AsyncMock(return_value=None),
    ) as mock_http:
        async with httpx.AsyncClient() as client:
            text, tier = await fetch_site_content(make_playwright_target(), client)

    mock_http.assert_not_called()
    mock_pw.assert_called_once()
    assert tier == "playwright"


@pytest.mark.asyncio
async def test_removes_script_and_style_tags():
    html = (
        "<html><body>"
        "<script>evil();</script>"
        "<style>.hide{display:none}</style>"
        "<p>Real content</p>"
        "</body></html>"
    )
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(200, text=html)
        )
        async with httpx.AsyncClient() as client:
            text, _ = await fetch_site_content(make_http_target(), client)

    assert "evil()" not in text
    assert ".hide" not in text
    assert "Real content" in text


@pytest.mark.asyncio
async def test_removes_nav_footer_header_tags():
    html = (
        "<html><body>"
        "<nav>Navigation</nav>"
        "<header>Site Header</header>"
        "<p>Job description here</p>"
        "<footer>Copyright 2024</footer>"
        "</body></html>"
    )
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(200, text=html)
        )
        async with httpx.AsyncClient() as client:
            text, _ = await fetch_site_content(make_http_target(), client)

    assert "Navigation" not in text
    assert "Site Header" not in text
    assert "Copyright 2024" not in text
    assert "Job description here" in text


@pytest.mark.asyncio
async def test_collapses_multiple_blank_lines():
    html = "<html><body><p>Line one</p>\n\n\n\n\n<p>Line two</p></body></html>"
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(200, text=html)
        )
        async with httpx.AsyncClient() as client:
            text, _ = await fetch_site_content(make_http_target(), client)

    import re
    assert not re.search(r"\n{3,}", text)


@pytest.mark.asyncio
async def test_returns_tier_name_in_tuple():
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(200, text="<html><body>ok</body></html>")
        )
        async with httpx.AsyncClient() as client:
            _, tier = await fetch_site_content(make_http_target(), client)
    assert tier == "http"
