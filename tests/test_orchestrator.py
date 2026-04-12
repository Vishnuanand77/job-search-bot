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
from job_scout.orchestrator import _build_page_url, run


@pytest.fixture
def mock_store():
    """Fixture that provides a properly configured JobStore mock."""
    with patch("job_scout.orchestrator.JobStore") as MockStore:
        store = MockStore.return_value
        store.is_new.return_value = True
        store.mark_seen.return_value = None
        store.get_last_run_at.return_value = None
        store.update_site_health.return_value = 0
        yield MockStore


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


def setup_store_mock(store: MagicMock) -> None:
    """Configure a JobStore mock with default return values."""
    store.is_new.return_value = True
    store.mark_seen.return_value = None
    store.get_last_run_at.return_value = None
    store.update_site_health.return_value = 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_processes_all_sites_in_config() -> None:
    config = make_config()
    jobs = [make_job()]

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(jobs, 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(None, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

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
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", side_effect=fetch_side_effect),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

        summary = await run(config)

    assert summary.sites_attempted == 2
    assert summary.sites_failed == 1
    assert summary.sites_succeeded == 1


@pytest.mark.asyncio
async def test_skips_jobs_already_in_dedup_store() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    jobs = [make_job()]

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
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
        store.get_last_run_at.return_value = None

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        await run(config)

    mock_match.assert_not_called()


@pytest.mark.asyncio
async def test_marks_all_new_jobs_as_seen_not_just_matches() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    jobs = [make_job("AI Engineer", job_id="job-001"), make_job("Data Scientist", job_id="job-002")]

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(jobs, 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(None, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

        await run(config)

    assert store.mark_seen.call_count == 2


@pytest.mark.asyncio
async def test_marks_matching_jobs_with_score() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    job = make_job()
    match = make_match(job)

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([job], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(match, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

        await run(config)

    store.mark_seen.assert_called_once_with(job, match_result=match)


@pytest.mark.asyncio
async def test_sends_digest_after_all_sites_processed() -> None:
    config = make_config()

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock) as mock_send,
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        await run(config)

    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_dry_run_skips_telegram_send() -> None:
    config = make_config(dry_run=True)

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock) as mock_send,
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
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
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(jobs, 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", side_effect=match_side_effect),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

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
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", side_effect=slow_fetch),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        await run(config)

    assert max(peak) <= 3


@pytest.mark.asyncio
async def test_per_site_errors_reported_in_digest_not_immediate_alert() -> None:
    """Per-site exceptions are caught and reported in the digest, not via immediate alerts."""
    config = make_config()

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, side_effect=Exception("boom")),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator.send_failure_alert", new_callable=AsyncMock) as mock_alert,
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        summary = await run(config)

    # Per-site exceptions are caught and included in run summary (reported via digest),
    # not sent as immediate alerts (prevents alert flooding)
    assert summary.sites_failed > 0
    assert summary.errors  # Errors appear in summary for digest inclusion
    mock_alert.assert_not_called()  # No immediate per-site alerts


@pytest.mark.asyncio
async def test_match_job_exception_passes_correct_job_count_to_health() -> None:
    """When match_job fails after extraction succeeds, don't mark site as having 0 jobs."""
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    jobs = [make_job("Job 1"), make_job("Job 2"), make_job("Job 3")]

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "playwright")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(jobs, 0.05)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, side_effect=Exception("API error")),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator.send_failure_alert", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

        summary = await run(config)

    # update_site_health should be called with actual job count (3), not 0
    store.update_site_health.assert_called_with("Stripe", 3)


@pytest.mark.asyncio
async def test_mark_seen_called_with_match_result_when_score_below_threshold() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    job = make_job()
    low_score_match = MatchResult(
        job=job,
        best_resume=ResumeProfile(role_label="AI Engineer", filename="ai_engineer.md", content="c"),
        best_score=0.40,
        match_reason="Weak fit.",
        missing_keywords=[],
        runner_up_resume=None,
        runner_up_score=None,
    )

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([job], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(low_score_match, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

        summary = await run(config)

    # mark_seen must receive the actual MatchResult even when score is below threshold
    store.mark_seen.assert_called_once_with(job, match_result=low_score_match)
    # But the low-score match must NOT appear in notifications
    assert len(summary.matches) == 0


@pytest.mark.asyncio
async def test_above_threshold_match_added_to_site_matches() -> None:
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])
    job = make_job()
    high_score_match = make_match(job)  # best_score=0.85, threshold=0.70

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([job], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(high_score_match, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

        summary = await run(config)

    assert len(summary.matches) == 1
    assert summary.matches[0].best_score == 0.85


# ---------------------------------------------------------------------------
# Pagination & multi-page orchestration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_page_site_fetches_exactly_once() -> None:
    # No pagination_param → range(1) → exactly 1 fetch
    config = make_config(sites=[SiteTarget("Stripe", "https://stripe.com/jobs", "http")])

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")) as mock_fetch,
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0
        store.get_last_run_at.return_value = None

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        await run(config)

    assert mock_fetch.call_count == 1


@pytest.mark.asyncio
async def test_paginated_site_fetches_up_to_max_pages() -> None:
    target = SiteTarget(
        name="Wells", url="https://wells.com/jobs", scrape_tier="http",
        pagination_param="start", pagination_step=20, max_pages=3,
    )
    config = make_config(sites=[target])

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")) as mock_fetch,
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator._detect_stop", return_value=False),
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0
        store.get_last_run_at.return_value = None

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        await run(config)

    assert mock_fetch.call_count == 3


@pytest.mark.asyncio
async def test_paginated_site_stops_early_when_detect_stop_returns_true() -> None:
    target = SiteTarget(
        name="Wells", url="https://wells.com/jobs", scrape_tier="http",
        pagination_param="start", pagination_step=20, max_pages=5,
    )
    config = make_config(sites=[target])

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")) as mock_fetch,
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator._detect_stop", return_value=True),
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0
        store.get_last_run_at.return_value = None

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        await run(config)

    # Stops after first page
    assert mock_fetch.call_count == 1


@pytest.mark.asyncio
async def test_page_zero_scraping_failure_returns_error_site_result() -> None:
    target = SiteTarget(
        name="Wells", url="https://wells.com/jobs", scrape_tier="http",
        pagination_param="start", pagination_step=20, max_pages=3,
    )
    config = make_config(sites=[target])

    from job_scout.scraper.dispatcher import ScrapingFailedError

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, side_effect=ScrapingFailedError("fail")),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0
        store.get_last_run_at.return_value = None

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        summary = await run(config)

    assert summary.sites_failed == 1
    assert summary.total_jobs_found == 0


@pytest.mark.asyncio
async def test_page_nonzero_scraping_failure_returns_partial_result() -> None:
    target = SiteTarget(
        name="Wells", url="https://wells.com/jobs", scrape_tier="http",
        pagination_param="start", pagination_step=20, max_pages=3,
    )
    config = make_config(sites=[target])

    from job_scout.scraper.dispatcher import ScrapingFailedError

    call_count = 0

    async def fetch_side_effect(*args, **kwargs) -> tuple[str, str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ("text", "http")
        raise ScrapingFailedError("page 1 failed")

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", side_effect=fetch_side_effect),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([make_job()], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(None, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator._detect_stop", return_value=False),
    ):
        store = MockStore.return_value
        setup_store_mock(store)

        summary = await run(config)

    # Site should succeed (partial) with jobs from page 0
    assert summary.sites_succeeded == 1
    assert summary.total_jobs_found == 1


@pytest.mark.asyncio
async def test_update_site_health_called_once_with_total_across_all_pages() -> None:
    target = SiteTarget(
        name="Wells", url="https://wells.com/jobs", scrape_tier="http",
        pagination_param="start", pagination_step=20, max_pages=3,
    )
    config = make_config(sites=[target])
    page_jobs = [make_job(job_id=f"job-{i}") for i in range(5)]

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=(page_jobs, 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.match_job", new_callable=AsyncMock, return_value=(None, 0.0)),
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator._detect_stop", return_value=False),
    ):
        store = MockStore.return_value
        store.is_new.return_value = False
        store.get_consecutive_zeros.return_value = 0
        store.get_last_run_at.return_value = None

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        await run(config)

    # 3 pages × 5 jobs = 15 total
    store.update_site_health.assert_called_once_with("Wells", 15)


@pytest.mark.asyncio
async def test_paginated_urls_increment_by_step() -> None:
    # Verify _build_page_url is called with correct offsets for each page
    target = SiteTarget(
        name="Wells", url="https://wells.com/jobs?pagesize=20", scrape_tier="http",
        pagination_param="start", pagination_step=20, max_pages=3,
    )
    config = make_config(sites=[target])
    fetched_urls: list[str] = []

    async def capture_fetch(site_target: SiteTarget, *args, **kwargs) -> tuple[str, str]:
        fetched_urls.append(site_target.url)
        return ("text", "http")

    with (
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", side_effect=capture_fetch),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator._detect_stop", return_value=False),
    ):
        store = MockStore.return_value
        store.get_consecutive_zeros.return_value = 0
        store.get_last_run_at.return_value = None

        store.update_site_health.return_value = 0
        store.mark_seen.return_value = None
        await run(config)

    assert len(fetched_urls) == 3
    assert "start=0" in fetched_urls[0]
    assert "start=20" in fetched_urls[1]
    assert "start=40" in fetched_urls[2]


@pytest.mark.asyncio
async def test_pagination_includes_jitter_between_requests() -> None:
    """Verify that jitter (1-3s sleep) is added between paginated page requests."""
    target = SiteTarget(
        name="Wells", url="https://wells.com/jobs", scrape_tier="http",
        pagination_param="start", pagination_step=20, max_pages=3,
    )
    config = make_config(sites=[target])

    # Mock async_playwright to avoid actual browser startup
    def mock_async_playwright_context():
        mock_pw = MagicMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_browser.__aexit__ = AsyncMock(return_value=None)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw.__aexit__ = AsyncMock(return_value=None)
        return mock_pw

    with (
        patch("job_scout.orchestrator.async_playwright", side_effect=mock_async_playwright_context),
        patch("job_scout.orchestrator.anthropic.AsyncAnthropic"),
        patch("job_scout.orchestrator.create_client"),
        patch("job_scout.orchestrator.fetch_site_content", new_callable=AsyncMock, return_value=("text", "http")),
        patch("job_scout.orchestrator.extract_jobs", new_callable=AsyncMock, return_value=([], 0.0)),
        patch("job_scout.orchestrator.JobStore") as MockStore,
        patch("job_scout.orchestrator.send_digest", new_callable=AsyncMock),
        patch("job_scout.orchestrator._detect_stop", return_value=False),
        patch("job_scout.orchestrator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        store = MockStore.return_value
        setup_store_mock(store)

        await run(config)

    # With max_pages=3 and pagination_param set, should sleep between pages:
    # After page 0, before page 1: sleep
    # After page 1, before page 2: sleep
    # After page 2: no sleep (last page)
    # So we expect 2 sleep calls
    assert mock_sleep.call_count == 2
