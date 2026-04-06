import logging
from collections import defaultdict
from datetime import datetime, timezone

import httpx

from job_scout.models import MatchResult, RunSummary

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_LEN = 4000


def format_digest(
    summary: RunSummary,
    stale_sites: dict[str, int] | None = None,
) -> list[str]:
    time_str = summary.run_at.strftime("%Y-%m-%d %H:%M")

    cost_str = f"${summary.total_cost_usd:.4f}"

    if not summary.matches:
        text = (
            f"✅ <b>Job Scout — no new matches</b>\n"
            f"<i>{time_str} UTC</i>\n\n"
            f"📊 Sites: {summary.sites_attempted} · "
            f"Jobs: {summary.total_jobs_found} · "
            f"New: {summary.new_jobs} · "
            f"Matches: 0\n"
            f"💰 Cost: {cost_str}"
        )
        if stale_sites:
            text += _stale_warnings(stale_sites)
        return [text]

    # Group matches by company
    by_company: dict[str, list[MatchResult]] = defaultdict(list)
    for m in summary.matches:
        by_company[m.job.company].append(m)

    header = (
        f"🔍 <b>Job Scout — {len(summary.matches)} new match(es)</b>\n"
        f"<i>{time_str} UTC</i>\n"
    )
    footer_lines = [
        "\n──────────────────",
        f"📊 <b>Run summary</b>",
        f"Sites: {summary.sites_attempted} checked · "
        f"{summary.sites_succeeded} OK · "
        f"{summary.sites_failed} failed",
        f"Jobs: {summary.total_jobs_found} found · "
        f"{summary.new_jobs} new · "
        f"{len(summary.matches)} matches",
        f"💰 Cost: {cost_str}",
    ]
    for err in summary.errors:
        footer_lines.append(f"⚠️ Failed: {err}")
    if stale_sites:
        footer_lines.append(_stale_warnings(stale_sites))
    footer = "\n".join(footer_lines)

    # Build per-company blocks
    company_blocks: list[str] = []
    for company, matches in by_company.items():
        lines = [f"\n<b>{company}</b>"]
        for m in matches:
            score_pct = f"{round(m.best_score * 100)}%"
            lines.append(
                f"├ 🎯 <b>{m.job.title}</b>\n"
                f"│  Resume: <i>{m.best_resume.role_label}</i> · Match: <b>{score_pct}</b>\n"
                f"│  {m.match_reason}"
            )
            if m.missing_keywords:
                lines.append(f"│  ⚠️ Missing: {', '.join(m.missing_keywords)}")
            if m.runner_up_resume and m.runner_up_score is not None:
                runner_pct = f"{round(m.runner_up_score * 100)}%"
                lines.append(
                    f"│  Runner-up: {m.runner_up_resume.role_label} · {runner_pct}"
                )
            lines.append(f"│  <a href=\"{m.job.url}\">View Job →</a>")
        company_blocks.append("\n".join(lines))

    # Split into messages at company boundaries if needed
    messages: list[str] = []
    current = header
    for block in company_blocks:
        candidate = current + block
        if len(candidate) > MAX_MESSAGE_LEN and current != header:
            messages.append(current)
            current = header + block
        else:
            current = candidate

    current += footer
    messages.append(current)
    return messages


def _stale_warnings(stale_sites: dict[str, int]) -> str:
    lines = []
    for site, zeros in stale_sites.items():
        if zeros >= 3:
            lines.append(
                f"\n⚠️ {site} has returned 0 jobs for {zeros} consecutive runs "
                f"— scraper may need updating"
            )
    return "".join(lines)


def format_failure_alert(error: Exception, context: str) -> str:
    time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return (
        f"🚨 <b>Job Scout — run failed</b>\n"
        f"<i>{time_str} UTC</i>\n\n"
        f"<b>Error:</b> {type(error).__name__}: {error}\n"
        f"<b>Context:</b> {context}\n\n"
        f"Check GitHub Actions logs for full traceback."
    )


async def send_digest(
    summary: RunSummary,
    bot_token: str,
    chat_id: str,
    dry_run: bool = False,
    stale_sites: dict[str, int] | None = None,
) -> None:
    parts = format_digest(summary, stale_sites=stale_sites)

    if dry_run:
        for i, part in enumerate(parts, 1):
            logger.info("Dry run — digest message %d/%d:\n%s", i, len(parts), part)
        return

    async with httpx.AsyncClient() as client:
        for part in parts:
            await _post(client, bot_token, chat_id, part)


async def send_failure_alert(
    error: Exception,
    context: str,
    bot_token: str,
    chat_id: str,
) -> None:
    text = format_failure_alert(error, context)
    async with httpx.AsyncClient() as client:
        await _post(client, bot_token, chat_id, text)


async def _post(
    client: httpx.AsyncClient,
    bot_token: str,
    chat_id: str,
    text: str,
) -> None:
    url = TELEGRAM_API.format(token=bot_token)
    response = await client.post(
        url,
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("Telegram HTTP error %s posting message: %s", exc.response.status_code, exc)
        return
    data = response.json()
    if not data.get("ok"):
        logger.error(
            "Telegram API returned ok=false: %s",
            data.get("description", "no description"),
        )
