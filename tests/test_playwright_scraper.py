import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from job_scout.scraper.playwright_scraper import fetch_html_with_browser


@pytest.mark.asyncio
async def test_returns_html_on_successful_navigation():
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html><body>Jobs</body></html>")
    mock_page.wait_for_load_state = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.__aenter__ = AsyncMock(return_value=mock_context)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "job_scout.scraper.playwright_scraper.async_playwright",
        return_value=mock_playwright,
    ):
        result = await fetch_html_with_browser("https://example.com/careers")

    assert result == "<html><body>Jobs</body></html>"


@pytest.mark.asyncio
async def test_returns_none_on_page_timeout():
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    mock_page = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock(
        side_effect=PlaywrightTimeoutError("timeout")
    )

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.__aenter__ = AsyncMock(return_value=mock_context)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "job_scout.scraper.playwright_scraper.async_playwright",
        return_value=mock_playwright,
    ):
        result = await fetch_html_with_browser("https://example.com/careers")

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_navigation_error():
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(side_effect=Exception("navigation failed"))

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.__aenter__ = AsyncMock(return_value=mock_context)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "job_scout.scraper.playwright_scraper.async_playwright",
        return_value=mock_playwright,
    ):
        result = await fetch_html_with_browser("https://example.com/careers")

    assert result is None


@pytest.mark.asyncio
async def test_closes_browser_when_exception_is_raised():
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(side_effect=Exception("crash"))

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.__aenter__ = AsyncMock(return_value=mock_context)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "job_scout.scraper.playwright_scraper.async_playwright",
        return_value=mock_playwright,
    ):
        result = await fetch_html_with_browser("https://example.com/careers")

    # The async context manager __aexit__ ensures cleanup — verify it was called
    mock_browser.__aexit__.assert_called_once()
    assert result is None


@pytest.mark.asyncio
async def test_sets_user_agent_on_browser_context():
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html></html>")
    mock_page.wait_for_load_state = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.__aenter__ = AsyncMock(return_value=mock_context)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "job_scout.scraper.playwright_scraper.async_playwright",
        return_value=mock_playwright,
    ):
        await fetch_html_with_browser("https://example.com/careers")

    call_kwargs = mock_browser.new_context.call_args
    assert call_kwargs is not None
    user_agent = call_kwargs.kwargs.get("user_agent") or (
        call_kwargs.args[0] if call_kwargs.args else None
    )
    assert user_agent is not None
    assert "Mozilla" in user_agent
