import httpx
import pytest
import respx

from job_scout.scraper.http_scraper import BROWSER_HEADERS, fetch_html


@pytest.mark.asyncio
async def test_returns_html_on_200_response():
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
        async with httpx.AsyncClient() as client:
            result = await fetch_html("https://example.com/careers", client)
    assert result == "<html><body>Jobs</body></html>"


@pytest.mark.asyncio
async def test_returns_none_on_403():
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(403)
        )
        async with httpx.AsyncClient() as client:
            result = await fetch_html("https://example.com/careers", client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_timeout():
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        async with httpx.AsyncClient() as client:
            result = await fetch_html("https://example.com/careers", client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_connection_error():
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        async with httpx.AsyncClient() as client:
            result = await fetch_html("https://example.com/careers", client)
    assert result is None


@pytest.mark.asyncio
async def test_request_includes_user_agent_header():
    with respx.mock:
        route = respx.get("https://example.com/careers").mock(
            return_value=httpx.Response(200, text="<html></html>")
        )
        async with httpx.AsyncClient() as client:
            await fetch_html("https://example.com/careers", client)
        sent_request = route.calls[0].request
    assert "Mozilla" in sent_request.headers["user-agent"]


@pytest.mark.asyncio
async def test_respects_30_second_timeout():
    with respx.mock:
        respx.get("https://example.com/careers").mock(
            side_effect=httpx.TimeoutException("timed out after 30s")
        )
        async with httpx.AsyncClient() as client:
            result = await fetch_html("https://example.com/careers", client)
    assert result is None


def test_browser_headers_contains_required_keys():
    assert "User-Agent" in BROWSER_HEADERS
    assert "Accept" in BROWSER_HEADERS
    assert "Accept-Language" in BROWSER_HEADERS
    assert "Accept-Encoding" in BROWSER_HEADERS
