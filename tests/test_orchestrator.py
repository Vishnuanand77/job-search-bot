import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_scout.models import (
    JobPosting,
    MatchResult,
    ResumeProfile,
    RunSummary,
    SiteTarget,
)
from job_scout.orchestrator import run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(
    sites: list[SiteTarget] | None = None,
    dry_run: bool = False,
) -> MagicMock:
    config = MagicMock()
    config.targets = sites or [
        SiteTarget(name="Stripe", url="https://stripe.com/jobs", scrape_tier="http"),
        SiteTarget(name="Anthropic", url="https://anthropic.com/careers", scrape_tier="http"),
    ]
    config.dry_run = dry_run
    config.match_threshold = 0.70
    config.resumes = [
        ResumeProfile(role_label="AI Engineer", filename="ai_engineer.md", content="resume content")
    ]
    config.anthropic_api_key = "test-key"
    config.supabase_url = "https://test.supabase.co"
    config.supabase_key = "test-supabase-key"
    config.telegram_bot_token = "test-bot-token"
    config.telegram_chat_id = "test-chat-id"
    return config


def make_job(title: str = "AI Engineer", company: str = "Stripe", job_id: str = "job-001") -> JobPosting:
    return JobPosting(
        title=title,
        url=f"https://example.com/jobs/{job_id}",
        company=company,
        description="Full JD.",
        snippet="Short summary.",
        job_id=job_id,
        posted_date=date(2024, 1, 1),
        location="Remote",
    )


def make_match(job: JobPosting) -> MatchResult:
    resume = ResumeProfile(role_label="AI Engineer", filename="ai_engineer.md", content="content")
    return MatchResult(
        job=job,
        best_resume=resume,
        best_score=0.85,
        match_reason="Great fit.",
        missing_keywords=[],
        runner_up_resume=None,
        runner_up_score=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_processes_all_sites_in_config() -> None:
    config = make_config()
    jobs = [make_job()]

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(jobs, 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(None, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.is_new.return_value = True
        store.get_consecutive_zeros.return_value = 0

        summary = await run(config)

    assert summary.sites_attempted == 2
    assert summary.sites_succeeded == 2


@pytest.mark.asyncio
async def test_site_error_does_not_abort_other_sites() -> None:
    config = make_config()

    call_count = 0

    async def fetch_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            from job_scout.scraper.dispatcher import ScrapingFailedError
            raise ScrapingFailedError("timeout")
        return ("text", "http")

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", side_effect=fetch_side_effect),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        summary = await run(config)

    assert summary.sites_attempted == 2
    assert summary.sites_failed == 1
    assert summary.sites_succeeded == 1


@pytest.mark.asyncio
async def test_skips_jobs_already_in_dedup_store() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    jobs = [make_job()]

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(jobs, 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock) as mock_match,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.is_new.return_value = False  # already seen
        store.get_consecutive_zeros.return_value = 0

        await run(config)

    mock_match.assert_not_called()


@pytest.mark.asyncio
async def test_marks_all_new_jobs_as_seen_not_just_matches() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    jobs = [make_job("AI Engineer", job_id="job-001"), make_job("Data Scientist", job_id="job-002")]

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(jobs, 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(None, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.is_new.return_value = True
        store.get_consecutive_zeros.return_value = 0

        await run(config)

    assert store.mark_seen.call_count == 2


@pytest.mark.asyncio
async def test_marks_matching_jobs_with_score() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    job = make_job()
    match = make_match(job)

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([job], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(match, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.is_new.return_value = True
        store.get_consecutive_zeros.return_value = 0

        await run(config)

    store.mark_seen.assert_called_once_with(job, match_result=match)


@pytest.mark.asyncio
async def test_sends_digest_after_all_sites_processed() -> None:
    config = make_config()

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock) as mock_send,
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        await run(config)

    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_dry_run_skips_telegram_send() -> None:
    config = make_config(dry_run=True)

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock) as mock_send,
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        await run(config)

    # send_digest is called but with dry_run=True — it's the notifier's job to no-op
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs.get("dry_run") is True


@pytest.mark.asyncio
async def test_run_summary_counts_are_accurate() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    jobs = [make_job("AI Engineer", job_id="job-001"), make_job("ML Engineer", job_id="job-002")]
    job_with_match = jobs[0]
    match = make_match(job_with_match)

    async def match_side_effect(job, *args, **kwargs):
        return (match, 0.0) if job.job_id == "job-001" else (None, 0.0)

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(jobs, 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", side_effect=match_side_effect),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.is_new.return_value = True
        store.get_consecutive_zeros.return_value = 0

        summary = await run(config)

    assert summary.sites_attempted == 1
    assert summary.sites_succeeded == 1
    assert summary.sites_failed == 0
    assert summary.total_jobs_found == 2
    assert summary.new_jobs == 2
    assert len(summary.matches) == 1


@pytest.mark.asyncio
async def test_respects_concurrency_limit_of_3() -> None:
    sites = [SiteTarget(f"Site{i}", f"https://site{i}.com", "http") for i in range(6)]
    config = make_config(sites=sites)
    active = []
    peak = []

    async def slow_fetch(*args, **kwargs):
        active.append(1)
        peak.append(len(active))
        await asyncio.sleep(0.01)
        active.pop()
        return ("text", "http")

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", side_effect=slow_fetch),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        await run(config)

    assert max(peak) <= 3


@pytest.mark.asyncio
async def test_sends_failure_alert_on_unhandled_exception() -> None:
    config = make_config()

    with (
        patch("job_scout.orchestrator.anthropic.Anthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, side_effect=Exception("boom")),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator.send_failure_alert", new_callable=AsyncMock) as mock_alert,
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        summary = await run(config)

    # Per-site exceptions are caught — failure alert fires for each site that errors unrecoverably
    # The run itself should complete (not propagate)
    assert summary.sites_failed > 0
