from datetime import date, time

import pytest

from job_scout.models import JobPosting, SiteTarget


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


# --- posted_time ---

def test_job_posting_posted_time_defaults_to_none() -> None:
    job = make_job()
    assert job.posted_time is None


def test_job_posting_accepts_posted_time() -> None:
    job = JobPosting(
        title="Engineer",
        url="https://example.com/jobs/1",
        company="Acme",
        description="desc",
        snippet="snip",
        job_id=None,
        posted_date=date(2024, 1, 15),
        posted_time=time(14, 30),
        location=None,
    )
    assert job.posted_time == time(14, 30)


# --- SiteTarget pagination fields ---

def test_site_target_pagination_param_defaults_to_none() -> None:
    target = SiteTarget(name="Test", url="https://example.com", scrape_tier="http")
    assert target.pagination_param is None


def test_site_target_pagination_step_defaults_to_20() -> None:
    target = SiteTarget(name="Test", url="https://example.com", scrape_tier="http")
    assert target.pagination_step == 20


def test_site_target_max_pages_defaults_to_5() -> None:
    target = SiteTarget(name="Test", url="https://example.com", scrape_tier="http")
    assert target.max_pages == 5


def test_site_target_accepts_pagination_config() -> None:
    target = SiteTarget(
        name="Wells Fargo",
        url="https://example.com/jobs",
        scrape_tier="http",
        pagination_param="start",
        pagination_step=20,
        max_pages=3,
    )
    assert target.pagination_param == "start"
    assert target.pagination_step == 20
    assert target.max_pages == 3
