import logging
from collections import defaultdict
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from job_scout.models import MatchResult, RunSummary

logger = logging.getLogger(__name__)

_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)

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
        "\n<b>Scoring guide:</b>",
        "0.9+ — Exceptional fit | 0.8–0.9 — Strong match | 0.7–0.8 — Learning opportunity",
    ]
    for err in summary.errors:
        footer_lines.append(f"⚠️ Failed: {err}")
    if stale_sites:
        footer_lines.append(_stale_warnings(stale_sites))
    footer = "\n".join(footer_lines)

    # Build messages by accumulating matches, respecting size limits
    messages: list[str] = []
    current = header
    footer_len = len(footer)
    current_company = None
    current_company_lines = []

    def format_match(m: MatchResult) -> str:
        """Format a single match as multiple lines."""
        score_pct = f"{round(m.best_score * 100)}%"
        lines = [
            f"├ 🎯 <b>{m.job.title}</b>\n"
            f"│  Resume: <i>{m.best_resume.role_label}</i> · Match: <b>{score_pct}</b>\n"
            f"│  {m.match_reason}"
        ]
        if m.missing_keywords:
            if 0.7 <= m.best_score < 0.9:
                lines.append(
                    f"│  🎓 <b>Learning opportunity:</b> {', '.join(m.missing_keywords)}"
                )
            else:
                lines.append(f"│  ⚠️ Missing: {', '.join(m.missing_keywords)}")
        if m.runner_up_resume and m.runner_up_score is not None:
            runner_pct = f"{round(m.runner_up_score * 100)}%"
            lines.append(
                f"│  Runner-up: {m.runner_up_resume.role_label} · {runner_pct}"
            )
        lines.append(f"│  <a href=\"{m.job.url}\">View Job →</a>")
        return "\n".join(lines)

    # Iterate through companies and matches
    for company, matches in by_company.items():
        company_header = f"\n<b>{company}</b>"

        for m in matches:
            match_text = format_match(m)

            # Check if adding this match would exceed limit (accounting for footer)
            test_current = current + company_header + match_text if company != current_company else current + match_text
            if len(test_current) + footer_len > MAX_MESSAGE_LEN and len(current) > len(header):
                # Current message is full; finalize and start new one
                if len(current) + footer_len <= MAX_MESSAGE_LEN:
                    current += footer
                messages.append(current)
                current = header
                current_company = None
                current_company_lines = []

                # Now try adding the company header and match to fresh message
                test_current = current + company_header + match_text
                if len(test_current) + footer_len > MAX_MESSAGE_LEN:
                    # Even fresh message can't hold this; add header and match as-is
                    # (company info + single match should fit in most cases)
                    current += company_header + match_text
                    current_company = company
                else:
                    current += company_header + match_text
                    current_company = company
            else:
                # Add to current message
                if company != current_company:
                    current += company_header
                    current_company = company
                current += match_text

    # Finalize last message with footer
    if len(current) + footer_len > MAX_MESSAGE_LEN:
        messages.append(current)
        current = header + footer
    else:
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


@_retry
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
        # For 429 (Too Many Requests), re-raise so @_retry handles it
        if exc.response.status_code == 429:
            retry_after = exc.response.headers.get("Retry-After", "60")
            try:
                wait_seconds = int(retry_after)
            except ValueError:
                # Retry-After can be an HTTP-date; default to 60s
                wait_seconds = 60
            logger.warning("Telegram rate limited (429); waiting %d seconds before retry", wait_seconds)
            raise

        logger.error("Telegram HTTP error %s posting message: %s", exc.response.status_code, exc)
        return
    data = response.json()
    if not data.get("ok"):
        logger.error(
            "Telegram API returned ok=false: %s",
            data.get("description", "no description"),
        )
