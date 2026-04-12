import json
import logging
from datetime import time
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock

import pytest

from job_scout.extractor.claude_extractor import extract_jobs
from job_scout.models import JobPosting


def _make_client(response_text: str) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = [MagicMock(text=response_text)]
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    client.messages.create = AsyncMock(return_value=message)
    return client


def _valid_job_json(
    title: str = "Software Engineer",
    url: str = "https://example.com/jobs/1",
    job_id: str | None = "job-123",
    description: str = "Full job description here.",
    snippet: str = "A great role.",
    posted_date: str | None = "2024-01-15",
    location: str | None = "Remote",
) -> dict:
    return {
        "title": title,
        "url": url,
        "job_id": job_id,
        "description": description,
        "snippet": snippet,
        "posted_date": posted_date,
        "location": location,
    }


# ---------------------------------------------------------------------------
# test_returns_list_of_job_postings_on_valid_response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_list_of_job_postings_on_valid_response():
    payload = json.dumps({"jobs": [_valid_job_json()]})
    client = _make_client(payload)

    jobs, cost = await extract_jobs("page content", "Acme", "https://example.com", client)

    assert len(jobs) == 1
    assert isinstance(jobs[0], JobPosting)
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].company == "Acme"


# ---------------------------------------------------------------------------
# test_returns_empty_list_when_claude_returns_no_jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_empty_list_when_claude_returns_no_jobs():
    client = _make_client(json.dumps({"jobs": []}))

    jobs, cost = await extract_jobs("page content", "Acme", "https://example.com", client)

    assert jobs == []


# ---------------------------------------------------------------------------
# test_returns_empty_list_on_json_parse_failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_empty_list_on_json_parse_failure():
    client = _make_client("not valid json at all")

    jobs, cost = await extract_jobs("page content", "Acme", "https://example.com", client)

    assert jobs == []


# ---------------------------------------------------------------------------
# test_logs_warning_on_json_parse_failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logs_warning_on_json_parse_failure(caplog):
    client = _make_client("not valid json at all")

    with caplog.at_level(logging.WARNING, logger="job_scout.extractor.claude_extractor"):
        await extract_jobs("page content", "Acme", "https://example.com", client)

    assert any("parse" in r.message.lower() or "json" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# test_dedup_key_set_to_job_id_when_present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedup_key_set_to_job_id_when_present():
    payload = json.dumps({"jobs": [_valid_job_json(job_id="abc-999")]})
    client = _make_client(payload)

    jobs, cost = await extract_jobs("content", "Acme", "https://example.com", client)

    assert jobs[0].dedup_key == "abc-999"
    assert jobs[0].dedup_type == "job_id"


# ---------------------------------------------------------------------------
# test_dedup_key_set_to_url_hash_when_no_job_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedup_key_set_to_url_hash_when_no_job_id():
    url = "https://example.com/jobs/42"
    payload = json.dumps({"jobs": [_valid_job_json(url=url, job_id=None)]})
    client = _make_client(payload)

    jobs, cost = await extract_jobs("content", "Acme", "https://example.com", client)

    expected = sha256(url.encode()).hexdigest()[:16]
    assert jobs[0].dedup_key == expected
    assert jobs[0].dedup_type == "url_hash"


# ---------------------------------------------------------------------------
# test_converts_relative_url_to_absolute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_converts_relative_url_to_absolute():
    payload = json.dumps({"jobs": [_valid_job_json(url="/jobs/99")]})
    client = _make_client(payload)

    jobs, cost = await extract_jobs("content", "Acme", "https://example.com", client)

    assert jobs[0].url.startswith("https://example.com")
    assert jobs[0].url == "https://example.com/jobs/99"


# ---------------------------------------------------------------------------
# test_caps_results_at_50_and_logs_warning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_caps_results_at_50_and_logs_warning(caplog):
    jobs = [_valid_job_json(title=f"Job {i}", url=f"https://example.com/jobs/{i}", job_id=str(i)) for i in range(60)]
    payload = json.dumps({"jobs": jobs})
    client = _make_client(payload)

    with caplog.at_level(logging.WARNING, logger="job_scout.extractor.claude_extractor"):
        jobs, cost = await extract_jobs("content", "Acme", "https://example.com", client)

    assert len(jobs) == 50
    assert any("50" in r.message or "cap" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# test_returns_empty_list_on_empty_content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_empty_list_on_empty_content():
    client = _make_client(json.dumps({"jobs": []}))

    jobs, cost = await extract_jobs("", "Acme", "https://example.com", client)

    assert jobs == []


# ---------------------------------------------------------------------------
# test_description_field_is_populated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_description_field_is_populated():
    desc = "We need a rockstar engineer who loves distributed systems."
    payload = json.dumps({"jobs": [_valid_job_json(description=desc)]})
    client = _make_client(payload)

    jobs, cost = await extract_jobs("content", "Acme", "https://example.com", client)

    assert jobs[0].description == desc


# ---------------------------------------------------------------------------
# test_handles_missing_url_in_job_entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handles_missing_url_in_job_entry():
    job = _valid_job_json()
    job["url"] = ""
    payload = json.dumps({"jobs": [job]})
    client = _make_client(payload)

    jobs, cost = await extract_jobs("content", "Acme", "https://example.com", client)

    assert jobs[0].url == "https://example.com"


# ---------------------------------------------------------------------------
# test_handles_invalid_posted_date_gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handles_invalid_posted_date_gracefully():
    job = _valid_job_json(posted_date="not-a-date")
    payload = json.dumps({"jobs": [job]})
    client = _make_client(payload)

    jobs, cost = await extract_jobs("content", "Acme", "https://example.com", client)

    assert jobs[0].posted_date is None


# ---------------------------------------------------------------------------
# test_handles_null_posted_date
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handles_null_posted_date():
    job = _valid_job_json(posted_date=None)
    payload = json.dumps({"jobs": [job]})
    client = _make_client(payload)

    jobs, cost = await extract_jobs("content", "Acme", "https://example.com", client)

    assert jobs[0].posted_date is None


# ---------------------------------------------------------------------------
# posted_time extraction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extracts_posted_time_when_present() -> None:
    job = {**_valid_job_json(), "posted_time": "14:30"}
    client = _make_client(json.dumps({"jobs": [job]}))
    jobs, _ = await extract_jobs("content", "Acme", "https://example.com", client)
    assert jobs[0].posted_time == time(14, 30)


@pytest.mark.asyncio
async def test_posted_time_accepts_hhmmss_format() -> None:
    job = {**_valid_job_json(), "posted_time": "09:15:00"}
    client = _make_client(json.dumps({"jobs": [job]}))
    jobs, _ = await extract_jobs("content", "Acme", "https://example.com", client)
    assert jobs[0].posted_time == time(9, 15, 0)


@pytest.mark.asyncio
async def test_posted_time_is_none_when_field_absent() -> None:
    client = _make_client(json.dumps({"jobs": [_valid_job_json()]}))
    jobs, _ = await extract_jobs("content", "Acme", "https://example.com", client)
    assert jobs[0].posted_time is None


@pytest.mark.asyncio
async def test_posted_time_is_none_when_field_is_null() -> None:
    job = {**_valid_job_json(), "posted_time": None}
    client = _make_client(json.dumps({"jobs": [job]}))
    jobs, _ = await extract_jobs("content", "Acme", "https://example.com", client)
    assert jobs[0].posted_time is None


@pytest.mark.asyncio
async def test_posted_time_is_none_when_field_is_invalid() -> None:
    job = {**_valid_job_json(), "posted_time": "not-a-time"}
    client = _make_client(json.dumps({"jobs": [job]}))
    jobs, _ = await extract_jobs("content", "Acme", "https://example.com", client)
    assert jobs[0].posted_time is None


@pytest.mark.asyncio
async def test_system_prompt_contains_posted_time_field() -> None:
    from job_scout.extractor.claude_extractor import SYSTEM_PROMPT
    assert "posted_time" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# test_returns_empty_list_on_empty_content_list_from_api
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_empty_list_on_empty_content_list_from_api():
    """Test graceful handling when Anthropic SDK returns empty content list."""
    client = MagicMock()
    message = MagicMock()
    message.content = []  # Empty content list triggers IndexError
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    client.messages.create = AsyncMock(return_value=message)

    jobs, cost = await extract_jobs("page content", "Acme", "https://example.com", client)

    assert jobs == []


@pytest.mark.asyncio
async def test_retries_on_transient_api_error(mocker):
    """Test that extract_jobs retries on transient errors then ultimately fails."""
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=Exception("API unavailable"))

    mocker.patch("tenacity.nap.time.sleep")

    with pytest.raises(Exception, match="API unavailable"):
        await extract_jobs("page content", "Acme", "https://example.com", client)

    # Should retry 3 times
    assert client.messages.create.call_count == 3
