from datetime import date
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
