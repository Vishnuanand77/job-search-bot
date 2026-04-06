# Job Scout

A Python cron job that scrapes company career pages, scores new job postings against role-specific resumes using Claude AI, and sends a Telegram digest of strong matches. Runs hourly via GitHub Actions.

## How it works

1. Scrapes configured career pages (HTTP with Playwright fallback for JS-heavy sites)
2. Extracts job listings using Claude Haiku
3. Deduplicates against a Supabase store
4. Scores each new job against all resumes using Claude Sonnet
5. Sends a Telegram digest grouped by company with scores and missing keywords

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)

### Install

```bash
uv sync --extra dev
uv run playwright install chromium --with-deps
```

### Configure

```bash
cp .env.example .env
# Fill in all values in .env
```

Required environment variables (see `.env.example`):

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon key |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Telegram chat ID to send digests to |
| `MATCH_THRESHOLD` | Minimum match score to notify (default: `0.70`) |
| `DRY_RUN` | If `true`, skips Telegram and Supabase writes (default: `false`) |

### Add target companies

Before adding a site, probe it to confirm which scraper tier works:

```bash
uv run python scripts/probe_sites.py https://example.com/careers
```

Then edit `config/targets.yaml`:

```yaml
sites:
  - name: Stripe
    url: https://stripe.com/jobs
    scrape_tier: http        # or 'playwright' for JS-heavy sites
```

### Add resumes

Place `.md` resume files in `resumes/`. Known filenames get mapped to display labels automatically:

| File | Label |
|---|---|
| `software_engineer_ai.md` | Software Engineer (AI Focused) |
| `ai_engineer.md` | AI Engineer |
| `data_scientist.md` | Data Scientist |

Any other `.md` file gets a title-cased label from its filename. No code changes needed.

## Running

```bash
# Dry run (no Telegram, no Supabase writes)
DRY_RUN=true uv run python -m job_scout.orchestrator

# Live run
uv run python -m job_scout.orchestrator
```

## Tests

```bash
uv run pytest
uv run pytest --cov=src --cov-report=html
```

## GitHub Actions

The workflow in `.github/workflows/scout.yml` runs every hour. Add the required secrets under **Settings → Secrets → Actions** in your repository.

## Supabase setup

Phase 5 requires two tables in your Supabase project. Run this SQL in the Supabase SQL editor:

```sql
create table seen_jobs (
  dedup_key text primary key,
  dedup_type text not null,
  title text,
  url text,
  company text,
  match_score float,
  seen_at timestamptz default now()
);

create table site_health (
  site_name text primary key,
  consecutive_zeros int not null default 0,
  last_success_at timestamptz
);
```
