import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from job_scout.matcher.claude_matcher import match_job
from job_scout.models import JobPosting, MatchResult, ResumeProfile


def make_job(description: str = "Full job description text.") -> JobPosting:
    return JobPosting(
        title="AI Engineer",
        url="https://example.com/jobs/ai-engineer",
        company="Example Corp",
        description=description,
        snippet="Short summary.",
        job_id="job-001",
        posted_date=date(2024, 1, 1),
        location="Remote",
    )


def make_resumes() -> list[ResumeProfile]:
    return [
        ResumeProfile(
            role_label="AI Engineer",
            filename="ai_engineer.md",
            content="Full resume content for AI Engineer role.",
        ),
        ResumeProfile(
            role_label="Software Engineer (AI Focused)",
            filename="software_engineer_ai.md",
            content="Full resume content for Software Engineer AI role.",
        ),
    ]


def make_claude_response(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = [MagicMock(text=json.dumps(payload))]
    message.usage.input_tokens = 500
    message.usage.output_tokens = 100
    return message


def make_client(payload: dict) -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=make_claude_response(payload))
    return client


@pytest.mark.asyncio
async def test_returns_match_result_when_score_meets_threshold() -> None:
    payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Strong Python and LLM experience.",
        "missing_keywords": ["MLOps"],
        "runner_up_filename": "software_engineer_ai.md",
        "runner_up_score": 0.72,
    }
    client = make_client(payload)
    result, cost = await match_job(make_job(), make_resumes(), client, threshold=0.70)
    assert isinstance(result, MatchResult)
    assert result.best_score == 0.85


@pytest.mark.asyncio
async def test_returns_none_when_score_below_threshold() -> None:
    payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.55,
        "match_reason": "Weak match.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = make_client(payload)
    result, cost = await match_job(make_job(), make_resumes(), client, threshold=0.70)
    assert result is None


@pytest.mark.asyncio
async def test_selects_correct_resume_profile_by_filename() -> None:
    payload = {
        "best_resume_filename": "software_engineer_ai.md",
        "best_score": 0.80,
        "match_reason": "Good match.",
        "missing_keywords": [],
        "runner_up_filename": "ai_engineer.md",
        "runner_up_score": 0.65,
    }
    client = make_client(payload)
    result, cost = await match_job(make_job(), make_resumes(), client, threshold=0.70)
    assert result is not None
    assert result.best_resume.filename == "software_engineer_ai.md"
    assert result.runner_up_resume is not None
    assert result.runner_up_resume.filename == "ai_engineer.md"


@pytest.mark.asyncio
async def test_returns_none_on_json_parse_failure() -> None:
    message = MagicMock()
    message.content = [MagicMock(text="not valid json {{{")]
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=message)
    result, cost = await match_job(make_job(), make_resumes(), client, threshold=0.70)
    assert result is None


@pytest.mark.asyncio
async def test_missing_keywords_is_a_list_of_strings() -> None:
    payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.90,
        "match_reason": "Excellent fit.",
        "missing_keywords": ["Kubernetes", "Ray", "Triton"],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = make_client(payload)
    result, cost = await match_job(make_job(), make_resumes(), client, threshold=0.70)
    assert result is not None
    assert result.missing_keywords == ["Kubernetes", "Ray", "Triton"]


@pytest.mark.asyncio
async def test_runner_up_is_none_when_only_one_resume() -> None:
    payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.80,
        "match_reason": "Only resume.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = make_client(payload)
    single_resume = [make_resumes()[0]]
    result, cost = await match_job(make_job(), single_resume, client, threshold=0.70)
    assert result is not None
    assert result.runner_up_resume is None
    assert result.runner_up_score is None


@pytest.mark.asyncio
async def test_returns_none_when_filename_not_in_loaded_resumes() -> None:
    payload = {
        "best_resume_filename": "nonexistent_resume.md",
        "best_score": 0.90,
        "match_reason": "Great match.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = make_client(payload)
    result, cost = await match_job(make_job(), make_resumes(), client, threshold=0.70)
    assert result is None


@pytest.mark.asyncio
async def test_full_description_passed_not_snippet() -> None:
    payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Good fit.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = make_client(payload)
    job = JobPosting(
        title="AI Engineer",
        url="https://example.com/jobs/1",
        company="Example Corp",
        description="FULL DESCRIPTION TEXT",
        snippet="SHORT SNIPPET",
        job_id="job-001",
        posted_date=date(2024, 1, 1),
        location="Remote",
    )
    await match_job(job, make_resumes(), client, threshold=0.70)
    call_kwargs = client.messages.create.call_args
    user_message = next(
        m["content"] for m in call_kwargs.kwargs["messages"] if m["role"] == "user"
    )
    assert "FULL DESCRIPTION TEXT" in user_message
    assert "SHORT SNIPPET" not in user_message


@pytest.mark.asyncio
async def test_full_resume_content_passed_not_truncated() -> None:
    long_content = "x" * 5000
    payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Good fit.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = make_client(payload)
    resumes = [
        ResumeProfile(
            role_label="AI Engineer",
            filename="ai_engineer.md",
            content=long_content,
        )
    ]
    await match_job(make_job(), resumes, client, threshold=0.70)
    call_kwargs = client.messages.create.call_args
    user_message = next(
        m["content"] for m in call_kwargs.kwargs["messages"] if m["role"] == "user"
    )
    assert long_content in user_message
