from datetime import date

import pytest

from job_scout.models import JobPosting


def make_job(job_id: str | None = None, url: str = "https://example.com/jobs/123") -> JobPosting:
    return JobPosting(
        title="Engineer",
        url=url,
        company="Acme",
        description="Full description text",
        snippet="Short summary",
        job_id=job_id,
        posted_date=None,
        location=None,
    )


def test_dedup_key_is_job_id_when_present() -> None:
    job = make_job(job_id="abc123")
    assert job.dedup_key == "abc123"


def test_dedup_key_is_url_hash_when_job_id_is_none() -> None:
    job = make_job(job_id=None)
    assert len(job.dedup_key) == 16


def test_dedup_key_is_url_hash_when_job_id_is_empty_string() -> None:
    job = make_job(job_id="")
    assert len(job.dedup_key) == 16


def test_dedup_type_is_job_id_when_job_id_present() -> None:
    job = make_job(job_id="abc123")
    assert job.dedup_type == "job_id"


def test_dedup_type_is_url_hash_when_job_id_absent() -> None:
    job = make_job(job_id=None)
    assert job.dedup_type == "url_hash"


def test_url_hash_is_deterministic_for_same_url() -> None:
    job1 = make_job(job_id=None, url="https://example.com/jobs/42")
    job2 = make_job(job_id=None, url="https://example.com/jobs/42")
    assert job1.dedup_key == job2.dedup_key


def test_url_hash_differs_for_different_urls() -> None:
    job1 = make_job(job_id=None, url="https://example.com/jobs/1")
    job2 = make_job(job_id=None, url="https://example.com/jobs/2")
    assert job1.dedup_key != job2.dedup_key


def test_url_hash_is_exactly_16_chars() -> None:
    job = make_job(job_id=None, url="https://example.com/jobs/999")
    assert len(job.dedup_key) == 16
