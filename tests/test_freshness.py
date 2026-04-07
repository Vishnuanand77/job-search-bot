from datetime import date, datetime, time, timedelta, timezone

import pytest

from job_scout.models import JobPosting
from job_scout.orchestrator import _detect_stop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LAST_RUN = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_job(
    posted_date: date | None = None,
    posted_time: time | None = None,
) -> JobPosting:
    return JobPosting(
        title="Engineer",
        url="https://example.com/job/1",
        company="Acme",
        description="desc",
        snippet="snip",
        job_id=None,
        posted_date=posted_date,
        posted_time=posted_time,
    )


# ---------------------------------------------------------------------------
# Always-stop / always-continue guards
# ---------------------------------------------------------------------------

def test_always_stops_on_empty_job_list() -> None:
    assert _detect_stop([], _LAST_RUN, 0) is True


def test_always_stops_on_empty_list_even_when_last_run_is_none() -> None:
    assert _detect_stop([], None, 0) is True


def test_always_continues_when_last_run_at_is_none() -> None:
    job = _make_job(posted_date=date(2020, 1, 1))
    assert _detect_stop([job], None, 0) is False


# ---------------------------------------------------------------------------
# Layer 1: posted_date + posted_time
# ---------------------------------------------------------------------------

def test_layer1_stops_when_all_timed_jobs_are_before_last_run() -> None:
    # All jobs posted well before last_run_at (noon on Jan 15)
    jobs = [
        _make_job(posted_date=date(2024, 1, 14), posted_time=time(8, 0)),
        _make_job(posted_date=date(2024, 1, 15), posted_time=time(10, 0)),
    ]
    assert _detect_stop(jobs, _LAST_RUN, 0) is True


def test_layer1_continues_when_any_timed_job_is_after_last_run() -> None:
    # One job posted after last_run_at (14:00 > 12:00 on same day)
    jobs = [
        _make_job(posted_date=date(2024, 1, 15), posted_time=time(14, 0)),
        _make_job(posted_date=date(2024, 1, 14), posted_time=time(8, 0)),
    ]
    assert _detect_stop(jobs, _LAST_RUN, 0) is False


def test_layer1_stops_when_all_timed_jobs_exactly_at_last_run_minus_one_second() -> None:
    # Strictly less than: a job at 11:59:59 is before noon
    jobs = [_make_job(posted_date=date(2024, 1, 15), posted_time=time(11, 59, 59))]
    assert _detect_stop(jobs, _LAST_RUN, 0) is True


def test_layer1_continues_when_timed_job_equals_last_run() -> None:
    # datetime.combine(...) == last_run_at is NOT strictly less, so should continue
    jobs = [_make_job(posted_date=date(2024, 1, 15), posted_time=time(12, 0, 0))]
    assert _detect_stop(jobs, _LAST_RUN, 0) is False


# ---------------------------------------------------------------------------
# Layer 2: posted_date only (no time)
# ---------------------------------------------------------------------------

def test_layer2_stops_when_all_dated_jobs_are_two_or_more_days_old() -> None:
    # cutoff = Jan 14; jobs from Jan 13 or earlier → stop
    jobs = [
        _make_job(posted_date=date(2024, 1, 13)),
        _make_job(posted_date=date(2024, 1, 12)),
    ]
    assert _detect_stop(jobs, _LAST_RUN, 0) is True


def test_layer2_continues_when_any_dated_job_is_from_yesterday() -> None:
    # cutoff = Jan 14; job on Jan 14 is NOT < Jan 14 → continue
    jobs = [_make_job(posted_date=date(2024, 1, 14))]
    assert _detect_stop(jobs, _LAST_RUN, 0) is False


def test_layer2_continues_when_any_dated_job_is_from_today() -> None:
    # Job posted same day as last_run_at → within-day ambiguity → continue
    jobs = [_make_job(posted_date=date(2024, 1, 15))]
    assert _detect_stop(jobs, _LAST_RUN, 0) is False


def test_layer2_continues_when_mix_of_old_and_recent_dates() -> None:
    # One old job + one from yesterday → all must be old to stop
    jobs = [
        _make_job(posted_date=date(2024, 1, 10)),
        _make_job(posted_date=date(2024, 1, 14)),
    ]
    assert _detect_stop(jobs, _LAST_RUN, 0) is False


# ---------------------------------------------------------------------------
# Layer 3: no dates at all
# ---------------------------------------------------------------------------

def test_layer3_stops_when_no_new_jobs_on_page() -> None:
    jobs = [_make_job()]  # no date, no time
    assert _detect_stop(jobs, _LAST_RUN, 0) is True


def test_layer3_continues_when_any_new_jobs_on_page() -> None:
    jobs = [_make_job()]  # no date, no time
    assert _detect_stop(jobs, _LAST_RUN, 3) is False
