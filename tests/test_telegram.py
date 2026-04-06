from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx

from job_scout.models import JobPosting, MatchResult, ResumeProfile, RunSummary
from job_scout.notifier.telegram import (
    format_digest,
    format_failure_alert,
    send_digest,
    send_failure_alert,
)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_resume(filename: str = "ai_engineer.md", label: str = "AI Engineer") -> ResumeProfile:
    return ResumeProfile(role_label=label, filename=filename, content="resume content")


def make_job(company: str = "Stripe", title: str = "Senior AI Engineer") -> JobPosting:
    return JobPosting(
        title=title,
        url="https://stripe.com/jobs/1",
        company=company,
        description="Full JD.",
        snippet="Short summary.",
        job_id="stripe-001",
        posted_date=date(2024, 1, 1),
        location="Remote",
    )


def make_match(
    company: str = "Stripe",
    title: str = "Senior AI Engineer",
    score: float = 0.87,
    missing: list[str] | None = None,
    runner_up_score: float | None = 0.74,
) -> MatchResult:
    job = make_job(company=company, title=title)
    resume = make_resume()
    runner_up = make_resume("software_engineer_ai.md", "Software Engineer (AI)") if runner_up_score else None
    return MatchResult(
        job=job,
        best_resume=resume,
        best_score=score,
        match_reason="Strong LLM alignment.",
        missing_keywords=missing or ["MLOps", "Kubeflow"],
        runner_up_resume=runner_up,
        runner_up_score=runner_up_score,
    )


def make_summary(
    matches: list[MatchResult] | None = None,
    errors: list[str] | None = None,
) -> RunSummary:
    return RunSummary(
        run_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        sites_attempted=10,
        sites_succeeded=9,
        sites_failed=1 if errors else 0,
        total_jobs_found=47,
        new_jobs=12,
        matches=matches or [],
        errors=errors or [],
    )


# ---------------------------------------------------------------------------
# format_digest
# ---------------------------------------------------------------------------

def test_formats_no_matches_digest_correctly() -> None:
    summary = make_summary(matches=[])
    parts = format_digest(summary)
    text = "\n".join(parts)
    assert "no new matches" in text.lower()
    assert "47" in text  # total jobs
    assert "12" in text  # new jobs


def test_matches_grouped_by_company() -> None:
    matches = [
        make_match(company="Stripe", title="AI Engineer"),
        make_match(company="Stripe", title="ML Engineer"),
        make_match(company="Anthropic", title="Research Engineer"),
    ]
    summary = make_summary(matches=matches)
    parts = format_digest(summary)
    text = "\n".join(parts)
    assert text.count("Stripe") >= 1
    assert text.count("Anthropic") >= 1


def test_missing_keywords_appear_in_digest() -> None:
    matches = [make_match(missing=["Kubernetes", "Triton"])]
    summary = make_summary(matches=matches)
    parts = format_digest(summary)
    text = "\n".join(parts)
    assert "Kubernetes" in text
    assert "Triton" in text


def test_runner_up_score_appears_in_digest() -> None:
    matches = [make_match(runner_up_score=0.74)]
    summary = make_summary(matches=matches)
    parts = format_digest(summary)
    text = "\n".join(parts)
    assert "74%" in text


def test_splits_long_digest_at_company_boundary() -> None:
    # Create enough matches to exceed 4000 chars
    matches = [
        make_match(
            company=f"Company{i}",
            title="Engineer " + "x" * 200,
            missing=["keyword"] * 8,
        )
        for i in range(20)
    ]
    summary = make_summary(matches=matches)
    parts = format_digest(summary)
    assert len(parts) > 1
    for part in parts:
        assert len(part) <= 4000


def test_stale_site_warning_appears_when_consecutive_zeros_gte_3() -> None:
    summary = make_summary()
    stale_sites = {"DeadCorp": 3, "GhostCo": 5}
    parts = format_digest(summary, stale_sites=stale_sites)
    text = "\n".join(parts)
    assert "DeadCorp" in text
    assert "GhostCo" in text
    assert "0 jobs" in text.lower() or "consecutive" in text.lower()


# ---------------------------------------------------------------------------
# format_failure_alert
# ---------------------------------------------------------------------------

def test_failure_alert_includes_error_type_and_message() -> None:
    error = ValueError("something went wrong")
    text = format_failure_alert(error, context="orchestrator startup")
    assert "ValueError" in text
    assert "something went wrong" in text
    assert "orchestrator startup" in text


# ---------------------------------------------------------------------------
# send_digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sends_to_correct_chat_id() -> None:
    summary = make_summary(matches=[make_match()])
    with respx.mock:
        route = respx.post("https://api.telegram.org/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {}})
        )
        await send_digest(summary, bot_token="TEST_TOKEN", chat_id="MY_CHAT_ID")
    assert route.called
    sent = route.calls[0].request
    import json
    body = json.loads(sent.content)
    assert body["chat_id"] == "MY_CHAT_ID"


@pytest.mark.asyncio
async def test_uses_html_parse_mode() -> None:
    summary = make_summary(matches=[make_match()])
    with respx.mock:
        route = respx.post("https://api.telegram.org/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {}})
        )
        await send_digest(summary, bot_token="TEST_TOKEN", chat_id="123")
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_checks_ok_field_in_response_body(caplog: pytest.LogCaptureFixture) -> None:
    summary = make_summary(matches=[make_match()])
    with respx.mock:
        respx.post("https://api.telegram.org/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": False, "description": "Bad Request"})
        )
        import logging
        with caplog.at_level(logging.ERROR, logger="job_scout.notifier.telegram"):
            await send_digest(summary, bot_token="TEST_TOKEN", chat_id="123")
    assert any("Bad Request" in r.message or "ok" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_logs_error_when_ok_is_false(caplog: pytest.LogCaptureFixture) -> None:
    summary = make_summary(matches=[make_match()])
    with respx.mock:
        respx.post("https://api.telegram.org/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": False, "description": "Forbidden"})
        )
        import logging
        with caplog.at_level(logging.ERROR, logger="job_scout.notifier.telegram"):
            await send_digest(summary, bot_token="TEST_TOKEN", chat_id="123")
    assert len(caplog.records) >= 1


@pytest.mark.asyncio
async def test_dry_run_does_not_call_telegram_api() -> None:
    summary = make_summary(matches=[make_match()])
    with respx.mock:
        respx.post("https://api.telegram.org/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        await send_digest(summary, bot_token="TEST_TOKEN", chat_id="123", dry_run=True)
        # No calls should have been made
        assert not respx.calls


@pytest.mark.asyncio
async def test_dry_run_logs_formatted_message(caplog: pytest.LogCaptureFixture) -> None:
    summary = make_summary(matches=[make_match()])
    with respx.mock:
        import logging
        with caplog.at_level(logging.INFO, logger="job_scout.notifier.telegram"):
            await send_digest(summary, bot_token="TEST_TOKEN", chat_id="123", dry_run=True)
    assert any("dry" in r.message.lower() or "digest" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_logs_error_when_telegram_returns_http_error(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    summary = make_summary(matches=[make_match()])
    with respx.mock:
        respx.post("https://api.telegram.org/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(429)
        )
        with caplog.at_level(logging.ERROR, logger="job_scout.notifier.telegram"):
            await send_digest(summary, bot_token="TEST_TOKEN", chat_id="123")
    assert any("429" in r.message or "http error" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_send_failure_alert_posts_to_telegram() -> None:
    error = RuntimeError("database connection failed")
    with respx.mock:
        route = respx.post("https://api.telegram.org/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {}})
        )
        await send_failure_alert(error, "orchestrator startup", bot_token="TEST_TOKEN", chat_id="123")
    assert route.called
    import json
    body = json.loads(route.calls[0].request.content)
    assert "RuntimeError" in body["text"]
    assert "database connection failed" in body["text"]
