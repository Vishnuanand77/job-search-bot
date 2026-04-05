# Job Scout — Setup Guide

Complete every step here before running the project for the first time.

---

## 1. Prerequisites

- Python 3.12+
- `uv` package manager
- A GitHub account
- Telegram on your phone

Install `uv`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 2. Install dependencies

```bash
uv sync --extra dev
uv run playwright install chromium --with-deps
```

---

## 3. Anthropic API Key

Used by Claude Haiku (extraction) and Claude Sonnet 4.6 (matching).

1. Go to https://console.anthropic.com
2. Sign in or create an account
3. Navigate to **API Keys** in the left sidebar
4. Click **Create Key** — name it `job-scout`
5. Copy the key immediately (starts with `sk-ant-`, shown only once)

Store as: `ANTHROPIC_API_KEY=sk-ant-...`

**Cost estimate:** Haiku for extraction + Sonnet for matching at 10 sites ×
~50 jobs × ~12 runs/day ≈ under $2/month.

---

## 4. Supabase Project

Used to track seen jobs and prevent duplicate notifications.

### Create the project
1. Go to https://supabase.com → **New Project** → name it `job-scout`
2. Choose a region close to you. Set a strong password.
3. Wait ~2 minutes for provisioning.

### Get credentials
1. Go to **Project Settings → API**
2. Copy **Project URL** → `SUPABASE_URL=https://xxx.supabase.co`
3. Copy **anon public** key → `SUPABASE_KEY=eyJ...`

### Create tables
Open **SQL Editor** in your Supabase dashboard and run:

```sql
CREATE TABLE seen_jobs (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    id_type         TEXT NOT NULL,
    posted_date     DATE,
    first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
    match_score     FLOAT,
    matched_resume  TEXT
);

CREATE INDEX idx_seen_jobs_first_seen ON seen_jobs(first_seen_at DESC);

CREATE TABLE site_health (
    site_name           TEXT PRIMARY KEY,
    consecutive_zeros   INT DEFAULT 0,
    last_success_at     TIMESTAMPTZ,
    last_checked_at     TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 5. Telegram Bot

### Create the bot
1. Open Telegram → search `@BotFather` (blue checkmark)
2. Send `/newbot`
3. Choose a display name: e.g. `Job Scout`
4. Choose a username ending in `bot`: e.g. `myjobscout_bot`
5. Copy the token BotFather sends you immediately

Store as: `TELEGRAM_BOT_TOKEN=123456789:AAF...`

### Get your Chat ID
1. Search for your bot in Telegram and send it any message (e.g. `/start`)
2. Open in browser: `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
3. Find `"chat": {"id": <number>}` in the response

Store as: `TELEGRAM_CHAT_ID=123456789`

---

## 6. Create your `.env` file

```bash
cp .env.example .env
```

Fill in all values. Never commit this file — it is already in `.gitignore`.

---

## 7. Add your resumes

Replace the placeholder files in `resumes/` with your actual resume content
in Markdown format:

```
resumes/
├── software_engineer_ai.md
├── ai_engineer.md
└── data_scientist.md
```

To convert your PDF resume to Markdown, paste it into Claude and ask:
> "Convert this resume to clean Markdown preserving all content."

Keep all content — the full text is used for job matching. No truncation.

Adding a 4th resume is automatic — just drop a new `.md` file in `resumes/`.

---

## 8. Configure target sites

Edit `config/targets.yaml` with your target career pages.
**Run `scripts/probe_sites.py` first** to find the right tier for each site.
See `docs/SCRAPER_PROBE.md` for instructions.

---

## 9. Add GitHub Actions secrets

Go to your repo → **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | From step 3 |
| `SUPABASE_URL` | From step 4 |
| `SUPABASE_KEY` | From step 4 |
| `TELEGRAM_BOT_TOKEN` | From step 5 |
| `TELEGRAM_CHAT_ID` | From step 5 |
| `MATCH_THRESHOLD` | `0.70` |

---

## 10. Verify setup

```bash
DRY_RUN=true uv run python -m job_scout.orchestrator
```

Check logs for config errors, scraping results, and the formatted Telegram
message. When satisfied, run live:

```bash
uv run python -m job_scout.orchestrator
```

You should receive a Telegram message within a minute.
