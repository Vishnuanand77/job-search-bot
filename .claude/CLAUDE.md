# Job Scout — Claude Code Project Context

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

You are building **Job Scout**: a Python cron job that scrapes company career pages, matches new postings against role-specific resumes using Claude AI, and sends Telegram notifications for strong matches.

Read this file completely before writing any code. These rules apply to every file in every phase without exception. You do not need to be reminded of them.

---

## Commands

```bash
# Install dependencies
uv sync --extra dev
uv run playwright install chromium --with-deps

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_models.py

# Run a single test by name
uv run pytest tests/test_models.py::test_dedup_key_is_job_id_when_present

# Coverage report
uv run pytest --cov=src --cov-report=html

# Dry run (no Telegram, no live writes)
DRY_RUN=true uv run python -m job_scout.orchestrator

# Live run
uv run python -m job_scout.orchestrator

# Probe a target site before adding it to targets.yaml
uv run python scripts/probe_sites.py
```

---

## Architecture

Job Scout is a single-pass pipeline triggered hourly via GitHub Actions:

```
load_config()
    └─ reads targets.yaml + resumes/*.md + env vars

asyncio.Semaphore(3) — concurrent per-site processing:
    fetch_site_content()       scraper/dispatcher.py
        ├─ http_scraper.py     httpx, BROWSER_HEADERS, 30s timeout
        └─ playwright_scraper.py  fallback for JS-heavy sites

    extract_jobs()             extractor/claude_extractor.py
        └─ claude-haiku-4-5, returns list[JobPosting]

    for each JobPosting:
        is_new()?              dedup/store.py  →  Supabase seen_jobs table
        match_job()            matcher/claude_matcher.py
            └─ claude-sonnet-4-6, scores all resumes, returns MatchResult | None
        mark_seen()            always, regardless of match score

build RunSummary → send_digest() / send_failure_alert()
    notifier/telegram.py       raw httpx POST, HTML parse_mode
```

- `dedup_key`: `job_id` if present, else `sha256(url)[:16]`. Set in `JobPosting.__post_init__`.
- All new jobs are marked seen even if below threshold — prevents re-evaluation on every run.
- `consecutive_zeros` in `site_health` table triggers stale-site warnings at ≥ 3.
- `resumes/*.md` files load at startup via `KNOWN_RESUME_LABELS` in `config.py`; unknown filenames get title-cased labels. Adding a resume requires zero code changes.
- Supabase tables: `seen_jobs` (primary key = `dedup_key`) and `site_health`. See `docs/SETUP.md` for SQL.
- Build proceeds phase-by-phase per `PLAN.md`. Each phase ends with `/pr-review` → PR → stop.

---

## Stack

| Concern | Tool |
|---|---|
| Language | Python 3.12 |
| Package manager | `uv` — never `pip` directly |
| HTTP client | `httpx` — never `requests` |
| Browser automation | `playwright` (async) |
| AI calls | `anthropic` SDK |
| Database | `supabase-py` |
| Testing | `pytest` + `pytest-asyncio` + `respx` + `pytest-mock` |
| Retries | `tenacity` |
| HTML parsing | `beautifulsoup4` with `html.parser` |

---

## Python Style

- Type hints on every function signature including return type. No exceptions.
- Dataclasses for all structured data passed between modules. No raw dicts.
- `pathlib.Path` everywhere. Never `os.path`.
- No module-level side effects. All I/O happens inside functions or
  constructors — never at import time.
- Constants in `UPPER_SNAKE_CASE` at the top of their module.
- `asyncio.gather` with `Semaphore(3)` for concurrent site scraping.
- All external calls must have explicit timeouts. `None` is never acceptable.
- `logging` module only. Never `print()`.
  Format: `%(asctime)s [%(levelname)s] %(name)s — %(message)s`
  Levels: INFO normal flow · DEBUG API payloads · WARNING recoverable ·
  ERROR unrecoverable

---

## Error Handling

- Never swallow exceptions silently. Every `except` must log and either
  re-raise or return a typed failure value.
- Per-site errors must not abort the full run. Catch, log, record in
  `RunSummary`, continue.
- All Anthropic, Supabase, and Telegram calls use `tenacity` retry:
  3 attempts, exponential backoff, base 1s, max 10s.
- HTTP 403 on scrape → escalate to next tier, not a fatal error.
- HTTP 429 → respect `Retry-After` header if present, else wait 60s.
- Any unhandled exception at orchestrator level → send Telegram failure
  alert before propagating.

---

## TDD — Red / Yellow / Green

Every piece of logic must be test-driven. No exceptions.

**Red:** Write a failing test specifying exactly what the function does.
Run it. Confirm it fails for the right reason — a real assertion failure.

**Yellow:** Write the minimal implementation to make that test pass.
Nothing extra. Run it — confirm it passes.

**Green:** Refactor if needed. Run all tests — confirm nothing regressed.

Show failing test output before writing implementation.
Show passing test output after.
Never write implementation before its test exists.

---

## Test Rules

- One test file per source module, mirroring source tree under `tests/`.
- `pytest-asyncio` for async tests. `asyncio_mode = "auto"` in `pyproject.toml`.
- No real HTTP, Supabase, or Anthropic calls in unit tests. Mock all I/O.
- `respx` for mocking `httpx`. `pytest-mock` for everything else.
- Test names describe behaviour: `test_returns_empty_list_when_no_jobs_found` ✓
- Minimum coverage: 80%. Run `pytest --cov` after each phase.

---

## HTTP / REST Rules

Always use these headers in every scraper:
```python
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}
```
- Random jitter 1–3s between requests to the same domain.
- Always `response.raise_for_status()` before reading body.
- Default scrape timeout: 30s. Never leave timeout unset.

---

## BeautifulSoup Rules

- Always `html.parser`. Switch to `lxml` only if provably needed.
- Prefer semantic selectors (`[role]`, `[aria-label]`, `[data-*]`) over
  fragile structural paths.
- Always `.strip()` extracted text.
- Always guard: `if tag := soup.find(...):` — never assume element exists.
- Before returning text, remove: `<script>`, `<style>`, `<nav>`,
  `<footer>`, `<header>`
- Extract: `soup.get_text(separator="\n", strip=True)`
- Collapse 3+ blank lines to one.

---

## Claude SDK Rules

- Extraction model: `claude-haiku-4-5` — structured parsing, cost matters.
- Matching model: `claude-sonnet-4-6` — reasoning task, quality matters.
- max_tokens: extraction `4096` · matching `2048`
- Always use a `system` prompt defining output format.
- Always request JSON. Parse with `json.loads()` inside try/except.
  Bad model output must never crash the run.
- Never log resume content beyond 200 chars.
- Instantiate `Anthropic` client once at startup. Pass as dependency.
  Never instantiate inside a loop.
- Pass full `job.description` to matching. No truncation.
- Pass full `resume.content` to matching. No truncation.

---

## Supabase Rules

- `supabase-py`. Instantiate once. Pass as dependency.
- Upsert for all `seen_jobs` writes — idempotent by design.
- Always check `response.data` — supabase-py does not raise on data errors.
- Never construct raw SQL. Query builder only.

---

## Telegram Rules

- No SDK. Raw `httpx` POST to:
  `https://api.telegram.org/bot{token}/sendMessage`
- Always `parse_mode: "HTML"`. Use `<b>`, `<i>`, `<a href="">`.
- Keep each message under 4096 chars. Split at company boundaries if over.
- Always check `response.json()["ok"]` — HTTP 200 does not mean success.
- Two types: digest (end of run) and failure alert (immediate on exception).

---

## Git Rules

After each phase: `git add -p` (never `git add .`), conventional commit,
open PR, run `/pr-review`, stop. Do not start next phase until PR approved.

Commit format: `feat(phase-N): short description`
