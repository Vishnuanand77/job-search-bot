from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from job_scout.dedup.store import JobStore
from job_scout.models import JobPosting, MatchResult, ResumeProfile


def make_job(job_id: str | None = "job-123", url: str = "https://example.com/jobs/123") -> JobPosting:
    return JobPosting(
        title="Software Engineer",
        url=url,
        company="Example Corp",
        description="Full job description here.",
        snippet="Short summary.",
        job_id=job_id,
        posted_date=date(2024, 1, 1),
        location="Remote",
    )


def make_match_result(job: JobPosting, score: float = 0.85) -> MatchResult:
    resume = ResumeProfile(
        role_label="AI Engineer",
        filename="ai_engineer.md",
        content="Resume content here.",
    )
    return MatchResult(
        job=job,
        best_resume=resume,
        best_score=score,
        match_reason="Strong alignment.",
        missing_keywords=["MLOps"],
        runner_up_resume=None,
        runner_up_score=None,
    )


def make_supabase_client(*, found: bool = False) -> MagicMock:
    client = MagicMock()
    # Chain: client.table(...).select(...).eq(...).execute()
    execute_result = MagicMock()
    execute_result.data = [{"dedup_key": "job-123"}] if found else []
    (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = execute_result

    upsert_result = MagicMock()
    upsert_result.data = [{}]
    client.table.return_value.upsert.return_value.execute.return_value = upsert_result

    return client


# --- is_new ---

def test_is_new_returns_true_when_job_not_in_store() -> None:
    client = make_supabase_client(found=False)
    store = JobStore(client)
    job = make_job()
    assert store.is_new(job) is True


def test_is_new_returns_false_when_job_already_seen() -> None:
    client = make_supabase_client(found=True)
    store = JobStore(client)
    job = make_job()
    assert store.is_new(job) is False


def test_is_new_uses_dedup_key_not_raw_url() -> None:
    client = make_supabase_client(found=False)
    store = JobStore(client)
    job = make_job(job_id="abc-999")
    store.is_new(job)
    # Verify the eq call used the dedup_key value
    client.table.return_value.select.return_value.eq.assert_called_once_with(
        "dedup_key", "abc-999"
    )


# --- mark_seen ---

def test_mark_seen_upserts_with_dedup_key_as_primary_key() -> None:
    client = make_supabase_client()
    store = JobStore(client)
    job = make_job()
    store.mark_seen(job)
    call_args = client.table.return_value.upsert.call_args
    data = call_args[0][0]
    assert data["dedup_key"] == job.dedup_key


def test_mark_seen_includes_match_score_when_match_provided() -> None:
    client = make_supabase_client()
    store = JobStore(client)
    job = make_job()
    match = make_match_result(job, score=0.88)
    store.mark_seen(job, match_result=match)
    call_args = client.table.return_value.upsert.call_args
    data = call_args[0][0]
    assert data["match_score"] == 0.88


def test_mark_seen_leaves_score_null_when_no_match() -> None:
    client = make_supabase_client()
    store = JobStore(client)
    job = make_job()
    store.mark_seen(job, match_result=None)
    call_args = client.table.return_value.upsert.call_args
    data = call_args[0][0]
    assert data["match_score"] is None


# --- update_site_health ---

def _make_client_for_site_health(*, consecutive_zeros: int = 0) -> MagicMock:
    client = MagicMock()
    # For get_consecutive_zeros
    select_result = MagicMock()
    select_result.data = [{"consecutive_zeros": consecutive_zeros}]
    (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = select_result

    upsert_result = MagicMock()
    upsert_result.data = [{}]
    client.table.return_value.upsert.return_value.execute.return_value = upsert_result

    return client


def test_update_site_health_increments_zeros_on_empty_result() -> None:
    client = _make_client_for_site_health(consecutive_zeros=2)
    store = JobStore(client)
    store.update_site_health("Example Corp", job_count=0)
    call_args = client.table.return_value.upsert.call_args
    data = call_args[0][0]
    assert data["consecutive_zeros"] == 3


def test_update_site_health_resets_zeros_on_non_empty_result() -> None:
    client = _make_client_for_site_health(consecutive_zeros=5)
    store = JobStore(client)
    store.update_site_health("Example Corp", job_count=10)
    call_args = client.table.return_value.upsert.call_args
    data = call_args[0][0]
    assert data["consecutive_zeros"] == 0


def test_update_site_health_does_not_overwrite_last_success_at_on_failure() -> None:
    client = _make_client_for_site_health(consecutive_zeros=1)
    store = JobStore(client)
    store.update_site_health("Example Corp", job_count=0)
    call_args = client.table.return_value.upsert.call_args
    data = call_args[0][0]
    assert "last_success_at" not in data


def test_update_site_health_returns_incremented_zeros() -> None:
    client = _make_client_for_site_health(consecutive_zeros=2)
    store = JobStore(client)
    result = store.update_site_health("Example Corp", job_count=0)
    assert result == 3


def test_update_site_health_returns_reset_zeros() -> None:
    client = _make_client_for_site_health(consecutive_zeros=5)
    store = JobStore(client)
    result = store.update_site_health("Example Corp", job_count=10)
    assert result == 0


# --- get_consecutive_zeros ---

def test_get_consecutive_zeros_returns_0_for_unknown_site() -> None:
    client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = []
    (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = execute_result
    store = JobStore(client)
    assert store.get_consecutive_zeros("Unknown Site") == 0


# --- get_last_run_at ---

def _make_client_for_last_run(*, last_success_at: str | None) -> MagicMock:
    client = MagicMock()
    execute_result = MagicMock()
    if last_success_at is None:
        execute_result.data = []
    else:
        execute_result.data = [{"last_success_at": last_success_at}]
    (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = execute_result
    return client


def test_get_last_run_at_returns_none_for_unknown_site() -> None:
    client = _make_client_for_last_run(last_success_at=None)
    store = JobStore(client)
    assert store.get_last_run_at("Unknown") is None


def test_get_last_run_at_returns_none_when_column_is_null() -> None:
    client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = [{"last_success_at": None}]
    (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = execute_result
    store = JobStore(client)
    assert store.get_last_run_at("Wells Fargo") is None


def test_get_last_run_at_returns_aware_datetime_for_known_site() -> None:
    ts = "2026-04-05T10:00:00+00:00"
    client = _make_client_for_last_run(last_success_at=ts)
    store = JobStore(client)
    result = store.get_last_run_at("Wells Fargo")
    assert result == datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)


def test_get_last_run_at_normalizes_naive_datetime_to_utc() -> None:
    ts = "2026-04-05T10:00:00"  # no timezone
    client = _make_client_for_last_run(last_success_at=ts)
    store = JobStore(client)
    result = store.get_last_run_at("Wells Fargo")
    assert result is not None
    assert result.tzinfo == timezone.utc
    assert result == datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)


def test_get_last_run_at_queries_correct_site_name() -> None:
    client = _make_client_for_last_run(last_success_at=None)
    store = JobStore(client)
    store.get_last_run_at("Capital One")
    client.table.return_value.select.return_value.eq.assert_called_once_with(
        "site_name", "Capital One"
    )


# --- Retry behavior ---

def test_is_new_retries_on_transient_failure(mocker) -> None:
    """Test that is_new retries on transient errors (but ultimately fails after 3 attempts)."""
    client = MagicMock()
    # Mock execute() to fail with a transient error (e.g., network timeout)
    client.table.return_value.select.return_value.eq.return_value.execute.side_effect = (
        Exception("Network timeout")
    )
    store = JobStore(client)

    # Patch sleep to avoid actual waits
    mocker.patch("tenacity.nap.time.sleep")

    # Verify that it retries 3 times then raises
    with pytest.raises(Exception, match="Network timeout"):
        store.is_new(make_job())

    # execute() should be called 3 times (3 retries)
    assert client.table.return_value.select.return_value.eq.return_value.execute.call_count == 3
