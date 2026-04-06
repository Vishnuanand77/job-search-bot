import json
import logging
from hashlib import sha256
from unittest.mock import MagicMock

import pytest

from job_scout.extractor.claude_extractor import extract_jobs
from job_scout.models import JobPosting


def _make_client(response_text: str) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = [MagicMock(text=response_text)]
    client.messages.create.return_value = message
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

    result = await extract_jobs("page content", "Acme", "https://example.com", client)

    assert len(result) == 1
    assert isinstance(result[0], JobPosting)
    assert result[0].title == "Software Engineer"
    assert result[0].company == "Acme"


# ---------------------------------------------------------------------------
# test_returns_empty_list_when_claude_returns_no_jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_empty_list_when_claude_returns_no_jobs():
    client = _make_client(json.dumps({"jobs": []}))

    result = await extract_jobs("page content", "Acme", "https://example.com", client)

    assert result == []


# ---------------------------------------------------------------------------
# test_returns_empty_list_on_json_parse_failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_empty_list_on_json_parse_failure():
    client = _make_client("not valid json at all")

    result = await extract_jobs("page content", "Acme", "https://example.com", client)

    assert result == []


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

    result = await extract_jobs("content", "Acme", "https://example.com", client)

    assert result[0].dedup_key == "abc-999"
    assert result[0].dedup_type == "job_id"


# ---------------------------------------------------------------------------
# test_dedup_key_set_to_url_hash_when_no_job_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedup_key_set_to_url_hash_when_no_job_id():
    url = "https://example.com/jobs/42"
    payload = json.dumps({"jobs": [_valid_job_json(url=url, job_id=None)]})
    client = _make_client(payload)

    result = await extract_jobs("content", "Acme", "https://example.com", client)

    expected = sha256(url.encode()).hexdigest()[:16]
    assert result[0].dedup_key == expected
    assert result[0].dedup_type == "url_hash"


# ---------------------------------------------------------------------------
# test_converts_relative_url_to_absolute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_converts_relative_url_to_absolute():
    payload = json.dumps({"jobs": [_valid_job_json(url="/jobs/99")]})
    client = _make_client(payload)

    result = await extract_jobs("content", "Acme", "https://example.com", client)

    assert result[0].url.startswith("https://example.com")
    assert result[0].url == "https://example.com/jobs/99"


# ---------------------------------------------------------------------------
# test_caps_results_at_50_and_logs_warning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_caps_results_at_50_and_logs_warning(caplog):
    jobs = [_valid_job_json(title=f"Job {i}", url=f"https://example.com/jobs/{i}", job_id=str(i)) for i in range(60)]
    payload = json.dumps({"jobs": jobs})
    client = _make_client(payload)

    with caplog.at_level(logging.WARNING, logger="job_scout.extractor.claude_extractor"):
        result = await extract_jobs("content", "Acme", "https://example.com", client)

    assert len(result) == 50
    assert any("50" in r.message or "cap" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# test_returns_empty_list_on_empty_content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_empty_list_on_empty_content():
    client = _make_client(json.dumps({"jobs": []}))

    result = await extract_jobs("", "Acme", "https://example.com", client)

    assert result == []


# ---------------------------------------------------------------------------
# test_description_field_is_populated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_description_field_is_populated():
    desc = "We need a rockstar engineer who loves distributed systems."
    payload = json.dumps({"jobs": [_valid_job_json(description=desc)]})
    client = _make_client(payload)

    result = await extract_jobs("content", "Acme", "https://example.com", client)

    assert result[0].description == desc


# ---------------------------------------------------------------------------
# test_handles_missing_url_in_job_entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handles_missing_url_in_job_entry():
    job = _valid_job_json()
    job["url"] = ""
    payload = json.dumps({"jobs": [job]})
    client = _make_client(payload)

    result = await extract_jobs("content", "Acme", "https://example.com", client)

    assert result[0].url == "https://example.com"


# ---------------------------------------------------------------------------
# test_handles_invalid_posted_date_gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handles_invalid_posted_date_gracefully():
    job = _valid_job_json(posted_date="not-a-date")
    payload = json.dumps({"jobs": [job]})
    client = _make_client(payload)

    result = await extract_jobs("content", "Acme", "https://example.com", client)

    assert result[0].posted_date is None


# ---------------------------------------------------------------------------
# test_handles_null_posted_date
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handles_null_posted_date():
    job = _valid_job_json(posted_date=None)
    payload = json.dumps({"jobs": [job]})
    client = _make_client(payload)

    result = await extract_jobs("content", "Acme", "https://example.com", client)

    assert result[0].posted_date is None
