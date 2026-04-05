# Job Scout — Claude Code Build Plan

Read `.claude/CLAUDE.md` first — it contains all coding standards, TDD rules, and API conventions that apply to every phase. Follow them automatically without being reminded in conversation.

At the end of each phase, run `/pr-review`, open a PR, and stop. Do not begin the next phase until the PR has been explicitly approved.

---

## Branch Strategy

Each phase lives on its own branch. Never commit phase work directly to `main`.

```bash
# Start a phase
git checkout main
git pull
git checkout -b phase-N-short-description

# During the phase: commit to the branch
git add -p
git commit -m "feat(phase-N): ..."

# End of phase: push, open PR targeting main, run /pr-review, stop
git push -u origin phase-N-short-description
```

Branch naming convention: `phase-N-<slug>` (e.g. `phase-2-config-models`, `phase-3-scraper`)

PRs must target `main`. Merge only after explicit approval. Delete the branch after merge.

---

## Project Purpose

A Python cron job running every hour via GitHub Actions that:
1. Scrapes company career pages (HTTP → Playwright fallback)
2. Extracts full job descriptions using Claude Haiku
3. Deduplicates against Supabase (Job ID → URL hash fallback)
4. Selects the best-fit resume from role-specific markdown files
5. Scores each new job against the matched resume using Claude Sonnet 4.6
6. Sends a Telegram digest grouped by company with scores, missing keywords,
   runner-up resume, and run summary stats
7. Sends an immediate Telegram failure alert on any unhandled exception

---

## Project Structure

```
job-scout/
├── .claude/
│   ├── CLAUDE.md
│   └── commands/
│       ├── pr-review.md
│       └── test.md
├── .github/
│   └── workflows/
│       └── scout.yml
├── resumes/
│   ├── software_engineer_ai.md
│   ├── ai_engineer.md
│   └── data_scientist.md
├── config/
│   └── targets.yaml
├── src/
│   └── job_scout/
│       ├── __init__.py
│       ├── config.py
│       ├── models.py
│       ├── scraper/
│       │   ├── __init__.py
│       │   ├── dispatcher.py
│       │   ├── http_scraper.py
│       │   └── playwright_scraper.py
│       ├── extractor/
│       │   ├── __init__.py
│       │   └── claude_extractor.py
│       ├── dedup/
│       │   ├── __init__.py
│       │   └── store.py
│       ├── matcher/
│       │   ├── __init__.py
│       │   └── claude_matcher.py
│       ├── notifier/
│       │   ├── __init__.py
│       │   └── telegram.py
│       └── orchestrator.py
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_http_scraper.py
│   ├── test_playwright_scraper.py
│   ├── test_dispatcher.py
│   ├── test_claude_extractor.py
│   ├── test_store.py
│   ├── test_claude_matcher.py
│   ├── test_telegram.py
│   └── test_orchestrator.py
├── scripts/
│   └── probe_sites.py
├── docs/
│   ├── SETUP.md
│   └── SCRAPER_PROBE.md
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## Data Models — Implement Before Any Other Module

Define all models in `src/job_scout/models.py` first. Every other module
imports from here. No other code is written until these are tested and passing.

```python
@dataclass
class SiteTarget:
    name: str
    url: str
    scrape_tier: str                  # 'http' or 'playwright'

@dataclass
class JobPosting:
    title: str
    url: str
    company: str
    description: str                  # full cleaned job description text
    snippet: str                      # 2-3 sentence summary for notifications
    job_id: str | None
    posted_date: date | None
    location: str | None
    dedup_key: str = field(init=False)
    dedup_type: str = field(init=False)

    def __post_init__(self) -> None:
        if self.job_id:
            self.dedup_key = self.job_id
            self.dedup_type = "job_id"
        else:
            self.dedup_key = sha256(self.url.encode()).hexdigest()[:16]
            self.dedup_type = "url_hash"

@dataclass
class ResumeProfile:
    role_label: str
    filename: str
    content: str                      # full markdown, no truncation

@dataclass
class MatchResult:
    job: JobPosting
    best_resume: ResumeProfile
    best_score: float
    match_reason: str
    missing_keywords: list[str]
    runner_up_resume: ResumeProfile | None
    runner_up_score: float | None

@dataclass
class SiteResult:
    site_name: str
    url: str
    jobs_found: int
    new_jobs: int
    matches: list[MatchResult]
    error: str | None
    scraper_tier_used: str

@dataclass
class RunSummary:
    run_at: datetime
    sites_attempted: int
    sites_succeeded: int
    sites_failed: int
    total_jobs_found: int
    new_jobs: int
    matches: list[MatchResult]
    errors: list[str]
```

---

## Phase 1 — Project Scaffold

**What:** Repository skeleton, tooling, placeholder files, CI workflow.
**Why first:** Every subsequent phase builds on this. Structural problems
caught here cost minutes; caught in Phase 6 they cost hours.

### Tasks

1. Initialise: `uv init job-scout --python 3.12`

2. `pyproject.toml`:
```toml
[project]
name = "job-scout"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.49.0",
    "httpx>=0.27.0",
    "beautifulsoup4>=4.12.0",
    "playwright>=1.44.0",
    "supabase>=2.5.0",
    "pydantic>=2.0.0",
    "pyyaml>=6.0.0",
    "tenacity>=8.0.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=5.0.0",
    "pytest-mock>=3.12.0",
    "respx>=0.21.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
source = ["src"]
omit = ["tests/*", "scripts/*"]
```

3. `.gitignore`: `.env`, `.cache/`, `__pycache__/`, `.pytest_cache/`,
   `htmlcov/`, `*.pyc`, `.playwright/`, `.venv/`, `dist/`, `*.egg-info/`
   Note: `resumes/*.md` is NOT gitignored.

4. `.env.example`:
```
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...
TELEGRAM_BOT_TOKEN=123456789:AAF...
TELEGRAM_CHAT_ID=123456789
MATCH_THRESHOLD=0.70
DRY_RUN=false
```

5. Create all stub `__init__.py` files and `pass`-body module placeholders
   so all imports resolve before any logic exists.

6. `config/targets.yaml` with 2 placeholder entries:
```yaml
sites:
  - name: Example Corp
    url: https://example.com/careers
    scrape_tier: http
  - name: Example Startup
    url: https://example.startup/jobs
    scrape_tier: playwright
```

7. `resumes/` with 3 placeholder `.md` files containing only a comment.

8. `.github/workflows/scout.yml`:
```yaml
name: Job Scout
on:
  schedule:
    - cron: '0 * * * *'
  workflow_dispatch:

jobs:
  scout:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Install dependencies
        run: uv sync --extra dev
      - name: Install Playwright
        run: uv run playwright install chromium --with-deps
      - name: Run job scout
        run: uv run python -m job_scout.orchestrator
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          MATCH_THRESHOLD: ${{ secrets.MATCH_THRESHOLD }}
          DRY_RUN: "false"
```

**Done condition:** `uv run pytest` runs with 0 tests, 0 errors.
Tree matches the structure exactly.

**Git:** branch `phase-1-scaffold` → `chore(phase-1): project scaffold` → `/pr-review` → PR → stop.

---

## Phase 2 — Config, Models, Resume Loader

**What:** Startup validation, shared data models, resume discovery.
**Why before scraping:** All other modules depend on these. Solid foundations
prevent cascading refactors later.

### 2a — `config.py`

```python
class ConfigurationError(Exception): ...

@dataclass
class AppConfig:
    anthropic_api_key: str
    supabase_url: str
    supabase_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    match_threshold: float      # default 0.70
    dry_run: bool               # default False
    targets: list[SiteTarget]
    resumes_dir: Path
    resumes: list[ResumeProfile]

def load_config() -> AppConfig: ...
```

- Raise `ConfigurationError` with the variable name for any missing required value.
- Reject `scrape_tier` values outside `['http', 'playwright']`.
- Raise if `targets` list is empty.
- Raise if no `.md` files found in `resumes/`.
- `match_threshold` defaults to `0.70`. `dry_run` defaults to `False`.

**Tests (Red → Yellow → Green for each):**
- `test_raises_configuration_error_on_missing_anthropic_key`
- `test_raises_configuration_error_on_missing_supabase_url`
- `test_raises_configuration_error_on_missing_telegram_token`
- `test_raises_on_invalid_scrape_tier`
- `test_raises_on_empty_targets_list`
- `test_raises_when_no_resumes_found`
- `test_match_threshold_defaults_to_0_70`
- `test_dry_run_defaults_to_false`
- `test_loads_targets_correctly_from_yaml`

### 2b — `models.py`

Implement all dataclasses from the Data Models section above.

**Tests (Red first):**
- `test_dedup_key_is_job_id_when_present`
- `test_dedup_key_is_url_hash_when_job_id_is_none`
- `test_dedup_key_is_url_hash_when_job_id_is_empty_string`
- `test_dedup_type_is_job_id_when_job_id_present`
- `test_dedup_type_is_url_hash_when_job_id_absent`
- `test_url_hash_is_deterministic_for_same_url`
- `test_url_hash_differs_for_different_urls`
- `test_url_hash_is_exactly_16_chars`

### 2c — Resume Loader (inside `config.py`)

Scan `resumes/` for `.md` files. Map filenames to role labels:

```python
KNOWN_RESUME_LABELS: dict[str, str] = {
    "software_engineer_ai.md": "Software Engineer (AI Focused)",
    "ai_engineer.md": "AI Engineer",
    "data_scientist.md": "Data Scientist",
}
# Fallback: strip .md, replace underscores with spaces, title-case
```

Adding a 4th `.md` file to `resumes/` requires zero code changes.

**Tests (Red first):**
- `test_loads_all_md_files_from_directory`
- `test_applies_correct_label_to_known_filename`
- `test_fallback_label_converts_filename_to_title_case`
- `test_resume_content_is_not_truncated`
- `test_returns_empty_list_when_directory_has_no_md_files`
- `test_raises_when_resume_directory_does_not_exist`

**Done condition:** All tests pass. `pytest --cov` ≥ 80%.
**Git:** branch `phase-2-config-models` → `feat(phase-2): config, models, resume loader` → `/pr-review` → PR → stop.

---

## Phase 3 — Scraper & Probe Tool

**What:** Two-tier scraper (HTTP → Playwright fallback) and a standalone
probe script for pre-testing sites before committing them to `targets.yaml`.
**Why highest-risk:** This component can fail for reasons entirely outside
your control. Validate against real URLs before building on top of it.

### 3a — `http_scraper.py`

```python
async def fetch_html(url: str, client: httpx.AsyncClient) -> str | None:
    # Returns raw HTML on success, None on 403/timeout/connection error
```

Use `BROWSER_HEADERS` as defined in `.claude/CLAUDE.md`. Timeout: 30s.

**Tests (Red first):**
- `test_returns_html_on_200_response`
- `test_returns_none_on_403`
- `test_returns_none_on_timeout`
- `test_returns_none_on_connection_error`
- `test_request_includes_user_agent_header`
- `test_respects_30_second_timeout`

### 3b — `playwright_scraper.py`

```python
async def fetch_html_with_browser(url: str) -> str | None:
    # Headless Chromium, waits for networkidle, returns HTML
    # Always cleans up — never leaks a browser process
```

Use `async with async_playwright()`. Wait: `page.wait_for_load_state("networkidle", timeout=15_000)`.

**Tests (Red first):**
- `test_returns_html_on_successful_navigation`
- `test_returns_none_on_page_timeout`
- `test_returns_none_on_navigation_error`
- `test_closes_browser_when_exception_is_raised`
- `test_sets_user_agent_on_browser_context`

### 3c — `dispatcher.py`

```python
class ScrapingFailedError(Exception): ...

async def fetch_site_content(
    target: SiteTarget,
    http_client: httpx.AsyncClient,
) -> tuple[str, str]:
    # Returns (cleaned_text, tier_used)
    # Raises ScrapingFailedError if all applicable tiers fail
```

Tier cascade:
- `scrape_tier = 'http'` → try HTTP → try Playwright → raise
- `scrape_tier = 'playwright'` → try Playwright only → raise

After successful fetch, clean the HTML:
1. Parse with BeautifulSoup `html.parser`
2. Remove `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`
3. `soup.get_text(separator="\n", strip=True)`
4. Collapse 3+ blank lines to one

**Tests (Red first):**
- `test_returns_http_content_when_http_succeeds`
- `test_falls_back_to_playwright_when_http_returns_none`
- `test_raises_scraping_failed_when_both_tiers_fail`
- `test_playwright_tier_does_not_attempt_http`
- `test_removes_script_and_style_tags`
- `test_removes_nav_footer_header_tags`
- `test_collapses_multiple_blank_lines`
- `test_returns_tier_name_in_tuple`

### 3d — `scripts/probe_sites.py`

Standalone manual tool. Not part of the test suite. No `.env` required.
Tests HTTP and Playwright access per URL and prints a recommended
`scrape_tier` ready to paste into `targets.yaml`.

See `docs/SCRAPER_PROBE.md` for full usage.

### Manual validation gate

**Run `probe_sites.py` against all 10 real target URLs before proceeding
to Phase 4. Update `targets.yaml` with confirmed tiers. Include probe
output in the Phase 3 PR body.**

**Done condition:** All scraper unit tests pass. Probe run completed.
`targets.yaml` reflects real confirmed tiers.
**Git:** branch `phase-3-scraper` → `feat(phase-3): scraper and probe tool` → `/pr-review` → PR → stop.

---

## Phase 4 — Job Extraction

**What:** Claude Haiku extracts structured job listings from scraped text.
**Why Claude not CSS selectors:** Every career site has different DOM
structure. Selectors break silently. A well-prompted Haiku call is
site-agnostic and resilient to layout changes.

### `claude_extractor.py`

```python
async def extract_jobs(
    content: str,
    company_name: str,
    site_url: str,
    client: anthropic.Anthropic,
) -> list[JobPosting]: ...
```

**Model:** `claude-haiku-4-5` | **max_tokens:** `4096`

**System prompt:**
```
You are a job listing extractor. You receive the text content of a company
careers page. Extract all visible job listings.

Return ONLY valid JSON — no preamble, no explanation, no markdown fences:
{
  "jobs": [
    {
      "title": "string",
      "url": "string — absolute URL; construct from base if relative",
      "job_id": "string or null — numeric/alphanumeric ID from URL or page",
      "description": "string — complete full text of the job description",
      "snippet": "string — 2-3 sentence summary of what this role does",
      "posted_date": "YYYY-MM-DD or null",
      "location": "string or null"
    }
  ]
}

Rules:
- Return {"jobs": []} if no listings are visible
- Never invent jobs — only extract what is explicitly listed
- description must be the full responsibilities and requirements text
- Convert relative dates to absolute using today's date
- Return only JSON
```

Cap at 50 jobs per site per run. Log WARNING if more than 50 returned.

**Tests (Red first):**
- `test_returns_list_of_job_postings_on_valid_response`
- `test_returns_empty_list_when_claude_returns_no_jobs`
- `test_returns_empty_list_on_json_parse_failure`
- `test_logs_warning_on_json_parse_failure`
- `test_dedup_key_set_to_job_id_when_present`
- `test_dedup_key_set_to_url_hash_when_no_job_id`
- `test_converts_relative_url_to_absolute`
- `test_caps_results_at_50_and_logs_warning`
- `test_returns_empty_list_on_empty_content`
- `test_description_field_is_populated`

**Done condition:** All tests pass. Manually verify extraction output against
one real page of scraped content from Phase 3.
**Git:** branch `phase-4-extractor` → `feat(phase-4): claude job extractor` → `/pr-review` → PR → stop.

---

## Phase 5 — Deduplication Store

**What:** Supabase-backed store tracking every seen job to prevent duplicate
notifications.

### `store.py`

```python
class JobStore:
    def __init__(self, client: Client) -> None: ...

    def is_new(self, job: JobPosting) -> bool:
        # Query seen_jobs by dedup_key. Returns True if not found.

    def mark_seen(
        self,
        job: JobPosting,
        match_result: MatchResult | None = None,
    ) -> None:
        # Upsert into seen_jobs. Include score if match_result provided.

    def update_site_health(self, site_name: str, job_count: int) -> None:
        # Increment consecutive_zeros if 0, else reset. Update last_success_at.

    def get_consecutive_zeros(self, site_name: str) -> int:
        # Return value from site_health, 0 if site not found.
```

Mark ALL new jobs as seen — not just matches. A below-threshold job must
not be re-evaluated on every subsequent run.

**Tests (Red first):**
- `test_is_new_returns_true_when_job_not_in_store`
- `test_is_new_returns_false_when_job_already_seen`
- `test_mark_seen_upserts_with_dedup_key_as_primary_key`
- `test_mark_seen_includes_match_score_when_match_provided`
- `test_mark_seen_leaves_score_null_when_no_match`
- `test_is_new_uses_dedup_key_not_raw_url`
- `test_update_site_health_increments_zeros_on_empty_result`
- `test_update_site_health_resets_zeros_on_non_empty_result`
- `test_get_consecutive_zeros_returns_0_for_unknown_site`

**Done condition:** All tests pass. Manually verify via Supabase dashboard.
**Git:** branch `phase-5-dedup` → `feat(phase-5): supabase dedup store` → `/pr-review` → PR → stop.

---

## Phase 6 — Resume Matching

**What:** Claude Sonnet 4.6 selects the best-fit resume, scores the match,
identifies missing keywords, provides a runner-up score.
**Why Sonnet:** Matching requires genuine reasoning about career alignment.
Quality difference over Haiku is meaningful. No truncation anywhere —
full JD and full resume content passed every time.

### `claude_matcher.py`

```python
async def match_job(
    job: JobPosting,
    resumes: list[ResumeProfile],
    client: anthropic.Anthropic,
    threshold: float,
) -> MatchResult | None:
    # Returns None if best_score < threshold
```

**Model:** `claude-sonnet-4-6` | **max_tokens:** `2048`

**System prompt:**
```
You are an expert technical recruiter evaluating resume-to-job fit.
You will receive a complete job description and multiple resumes.

Tasks:
1. Identify which resume is the strongest fit for this role
2. Score that fit 0.0 to 1.0
3. Score the second-best resume
4. List keywords in the JD absent from the best-fit resume

Return ONLY valid JSON — no preamble:
{
  "best_resume_filename": "string",
  "best_score": 0.85,
  "match_reason": "string — one concise sentence",
  "missing_keywords": ["keyword1", "keyword2"],
  "runner_up_filename": "string or null",
  "runner_up_score": 0.72
}

Scoring: 0.9+ exceptional · 0.75–0.9 strong · 0.6–0.75 moderate · <0.6 weak
missing_keywords: up to 8 important technical skills/tools explicitly required
but absent from the best resume. Only genuinely important gaps.
```

**User message:** Full `job.description` + full `resume.content` for each
resume. No truncation of either.

**Tests (Red first):**
- `test_returns_match_result_when_score_meets_threshold`
- `test_returns_none_when_score_below_threshold`
- `test_selects_correct_resume_profile_by_filename`
- `test_returns_none_on_json_parse_failure`
- `test_missing_keywords_is_a_list_of_strings`
- `test_runner_up_is_none_when_only_one_resume`
- `test_returns_none_when_filename_not_in_loaded_resumes`
- `test_full_description_passed_not_snippet`
- `test_full_resume_content_passed_not_truncated`

**Done condition:** All tests pass. Manually test on one real job posting
with your actual resumes. Verify scores and missing keywords are sensible.
**Git:** branch `phase-6-matcher` → `feat(phase-6): claude resume matcher` → `/pr-review` → PR → stop.

---

## Phase 7 — Telegram Notifier

**What:** Two notification types — run digest and immediate failure alert.

### `telegram.py`

```python
async def send_digest(
    summary: RunSummary,
    bot_token: str,
    chat_id: str,
    dry_run: bool = False,
) -> None: ...

async def send_failure_alert(
    error: Exception,
    context: str,
    bot_token: str,
    chat_id: str,
) -> None: ...

def format_digest(summary: RunSummary) -> list[str]:
    # List of strings — split at company boundaries if > 4000 chars

def format_failure_alert(error: Exception, context: str) -> str: ...
```

**Digest — matches found:**
```
🔍 <b>Job Scout — {N} new match(es)</b>
<i>{time} UTC</i>

<b>Stripe</b>
├ 🎯 <b>Senior Engineer, AI Platform</b>
│  Resume: <i>AI Engineer</i> · Match: <b>87%</b>
│  Strong Python and LLM infrastructure alignment
│  ⚠️ Missing: MLOps, Kubeflow, feature stores
│  Runner-up: Software Engineer (AI) · 74%
│  <a href="{url}">View Job →</a>

──────────────────
📊 <b>Run summary</b>
Sites: 10 checked · 9 OK · 1 failed
Jobs: 47 found · 12 new · 2 matches
⚠️ Failed: Example Corp — timeout
```

**Digest — no matches:**
```
✅ <b>Job Scout — no new matches</b>
<i>{time} UTC</i>

📊 Sites: 10 · Jobs: 47 · New: 8 · Matches: 0
```

**Failure alert:**
```
🚨 <b>Job Scout — run failed</b>
<i>{time} UTC</i>

<b>Error:</b> {ErrorType}: {message}
<b>Context:</b> {context}

Check GitHub Actions logs for full traceback.
```

**Stale site warning:** Append to digest when `consecutive_zeros >= 3`:
`⚠️ {site} has returned 0 jobs for 3 consecutive runs — scraper may need updating`

**Rules:**
- `parse_mode: "HTML"` always. Never Markdown.
- Split messages at company boundaries if > 4000 chars.
- Dry run: log formatted message, never call the API.
- Always check `response.json()["ok"]` — Telegram returns HTTP 200 for errors.

**Tests (Red first):**
- `test_sends_to_correct_chat_id`
- `test_uses_html_parse_mode`
- `test_checks_ok_field_in_response_body`
- `test_logs_error_when_ok_is_false`
- `test_dry_run_does_not_call_telegram_api`
- `test_dry_run_logs_formatted_message`
- `test_splits_long_digest_at_company_boundary`
- `test_formats_no_matches_digest_correctly`
- `test_matches_grouped_by_company`
- `test_missing_keywords_appear_in_digest`
- `test_runner_up_score_appears_in_digest`
- `test_failure_alert_includes_error_type_and_message`
- `test_stale_site_warning_appears_when_consecutive_zeros_gte_3`

**Done condition:** All tests pass. Send a live test digest and failure
alert to your real Telegram bot.
**Git:** branch `phase-7-notifier` → `feat(phase-7): telegram notifier` → `/pr-review` → PR → stop.

---

## Phase 8 — Orchestrator

**What:** Main run loop wiring all components together.

### `orchestrator.py`

```python
async def run(config: AppConfig) -> RunSummary: ...

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    try:
        config = load_config()
        summary = asyncio.run(run(config))
        sys.exit(0 if summary.sites_failed == 0 else 1)
    except Exception as e:
        asyncio.run(send_failure_alert(
            error=e,
            context="orchestrator startup",
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        ))
        raise

if __name__ == "__main__":
    main()
```

**Run loop:**
```
1. Load config — Telegram alert if fails
2. Initialise Anthropic client (once)
3. Initialise Supabase client (once)
4. Initialise httpx.AsyncClient with 30s timeout (once)

Process all sites concurrently via asyncio.Semaphore(3):

  For each site:
    a. fetch_site_content → (text, tier) or catch ScrapingFailedError
    b. extract_jobs → list[JobPosting]
    c. update_site_health(site_name, len(jobs))
    d. For each job:
         i.   is_new? → skip if False
         ii.  match_job → MatchResult | None
         iii. mark_seen (with or without score)
         iv.  if match → add to site matches
    e. Record SiteResult

5. Build RunSummary
6. Check consecutive_zeros → attach stale warnings
7. send_digest (or log if dry_run)
8. Return RunSummary
```

Any exception escaping per-site handling → `send_failure_alert` before propagating.

**Tests (Red first):**
- `test_processes_all_sites_in_config`
- `test_site_error_does_not_abort_other_sites`
- `test_skips_jobs_already_in_dedup_store`
- `test_marks_all_new_jobs_as_seen_not_just_matches`
- `test_marks_matching_jobs_with_score`
- `test_respects_concurrency_limit_of_3`
- `test_sends_digest_after_all_sites_processed`
- `test_dry_run_skips_telegram_send`
- `test_run_summary_counts_are_accurate`
- `test_exits_with_code_1_when_any_site_failed`
- `test_sends_failure_alert_on_unhandled_exception`

**Done condition:** All tests pass. Full dry run:
`DRY_RUN=true uv run python -m job_scout.orchestrator`
**Git:** branch `phase-8-orchestrator` → `feat(phase-8): orchestrator` → `/pr-review` → PR → stop.

---

## Phase 9 — End-to-End Validation

**What:** Live integration test. Manual, not automated.

1. Replace placeholder resume `.md` files with your actual resume content.
2. Replace `targets.yaml` with your 10 real sites (tiers from Phase 3 probe).
3. Dry run: `DRY_RUN=true uv run python -m job_scout.orchestrator`
   - Verify all sites attempted, jobs extracted, dedup working, scores sensible
   - Run twice — second run must show 0 new jobs
4. Live run: `uv run python -m job_scout.orchestrator`
   - Receive Telegram digest on your phone
   - Check Supabase `seen_jobs` table has rows
5. Trigger GitHub Actions manually → confirm green run + Telegram message.

**Done condition:** Live message received. Supabase populated. Actions green.
**Git:** branch `phase-9-live-validation` → `chore(phase-9): live targets and resumes` → PR → stop.

---

## Phase 10 — Hardening

**What:** Production resilience.

### 10a — Retry audit
Verify `tenacity` retry decorators (3 attempts, exponential backoff, 1s–10s) on:
- All `client.messages.create` calls
- All Supabase `.execute()` calls
- All `send_digest` and `send_failure_alert` calls

Not on scraper fetches — failure there triggers tier escalation, not retry.

### 10b — Token budget guard
Before each Anthropic call: `estimated = len(content) // 4`
If `estimated > 60_000` → log ERROR, skip the call rather than risk a
runaway bill. This catches cases where a page returns garbage at scale.

**Tests:**
- `test_skips_extraction_and_logs_error_when_content_abnormally_large`

### 10c — Per-site logging
After each site:
```
[Stripe] tier=http jobs=23 new=4 matches=1 duration=2.3s
[AmEx] tier=playwright jobs=8 new=0 matches=0 duration=8.1s
[BrokenSite] FAILED timeout after 30s
```

### 10d — Final coverage
`uv run pytest --cov=src --cov-report=html`
Cover any uncovered critical paths. Target: ≥ 85%.

**Done condition:** All hardening tests pass. Coverage ≥ 85%.
Clean live end-to-end run. Production-ready v1.0.
**Git:** branch `phase-10-hardening` → `feat(phase-10): hardening` → `/pr-review` → Final PR.

---

## GitHub Actions Secrets

Repo → Settings → Secrets → Actions → New repository secret:

| Secret | Source |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Console |
| `SUPABASE_URL` | Supabase project settings |
| `SUPABASE_KEY` | Supabase anon key |
| `TELEGRAM_BOT_TOKEN` | BotFather |
| `TELEGRAM_CHAT_ID` | getUpdates call |
| `MATCH_THRESHOLD` | `0.70` to start |

---

## Final instruction to Claude Code

Work strictly phase by phase. Do not begin a phase until the previous PR
is approved. Always create a fresh branch from `main` before starting a phase.
Always show failing test output before writing implementation. Always show
passing output after. Never `git add .` — always `git add -p`. Stop and ask
when any architectural decision is unclear.
