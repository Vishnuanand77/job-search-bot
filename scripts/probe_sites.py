"""
probe_sites.py — manually test HTTP and Playwright access to career pages.

Usage:
    uv run python scripts/probe_sites.py [URL ...]

If no URLs are provided, reads from config/targets.yaml.

Output: per-URL result with recommended scrape_tier ready to paste into targets.yaml.
"""

import asyncio
import sys
import time
from pathlib import Path

import httpx
import yaml


# Ensure src/ is importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from job_scout.scraper.http_scraper import BROWSER_HEADERS, SCRAPE_TIMEOUT  # noqa: E402
from job_scout.scraper.playwright_scraper import fetch_html_with_browser  # noqa: E402

TARGETS_YAML = Path(__file__).parent.parent / "config" / "targets.yaml"


def _load_urls_from_yaml() -> list[tuple[str, str]]:
    """Return list of (name, url) pairs from targets.yaml."""
    with TARGETS_YAML.open() as f:
        data = yaml.safe_load(f)
    return [(site["name"], site["url"]) for site in data.get("sites", [])]


async def probe_http(url: str) -> tuple[bool, int, float]:
    """Return (success, status_code, elapsed_seconds)."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=BROWSER_HEADERS, timeout=SCRAPE_TIMEOUT)
        elapsed = time.monotonic() - start
        return response.status_code == 200, response.status_code, elapsed
    except Exception as exc:
        elapsed = time.monotonic() - start
        print(f"    HTTP error: {exc}")
        return False, 0, elapsed


async def probe_playwright(url: str) -> tuple[bool, float]:
    """Return (success, elapsed_seconds)."""
    start = time.monotonic()
    html = await fetch_html_with_browser(url)
    elapsed = time.monotonic() - start
    return html is not None and len(html) > 200, elapsed


async def probe_one(name: str, url: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {name}")
    print(f"  {url}")
    print(f"{'─' * 60}")

    print("  [HTTP] probing...")
    http_ok, http_status, http_elapsed = await probe_http(url)
    http_label = f"✓ {http_status} ({http_elapsed:.1f}s)" if http_ok else f"✗ status={http_status} ({http_elapsed:.1f}s)"
    print(f"  [HTTP] {http_label}")

    print("  [Playwright] probing...")
    pw_ok, pw_elapsed = await probe_playwright(url)
    pw_label = f"✓ content received ({pw_elapsed:.1f}s)" if pw_ok else f"✗ failed ({pw_elapsed:.1f}s)"
    print(f"  [Playwright] {pw_label}")

    if http_ok:
        recommended = "http"
    elif pw_ok:
        recommended = "playwright"
    else:
        recommended = "FAILED — check manually"

    print(f"\n  → Recommended scrape_tier: {recommended}")
    print(f"    - name: {name}")
    print(f"      url: {url}")
    print(f"      scrape_tier: {recommended}")


async def main(argv: list[str]) -> None:
    if argv:
        targets = [(url, url) for url in argv]
    elif TARGETS_YAML.exists():
        targets = _load_urls_from_yaml()
    else:
        print("No URLs provided and config/targets.yaml not found.")
        print("Usage: uv run python scripts/probe_sites.py [URL ...]")
        sys.exit(1)

    print(f"Probing {len(targets)} site(s)...\n")
    for name, url in targets:
        await probe_one(name, url)

    print(f"\n{'═' * 60}")
    print("Probe complete. Copy the scrape_tier recommendations above into")
    print("config/targets.yaml.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
