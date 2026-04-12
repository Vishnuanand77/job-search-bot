import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from job_scout.matcher.claude_matcher import JobRole, classify_job_role, match_job
from job_scout.models import JobPosting, MatchResult, ResumeProfile


def make_job(
    description: str = "Full job description text.",
    title: str = "AI Engineer",
) -> JobPosting:
    return JobPosting(
        title=title,
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


# =============================================================================
# Tests for classify_job_role (Stage 1)
# =============================================================================


@pytest.mark.asyncio
async def test_classify_job_role_identifies_ai_engineer() -> None:
    payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "Mentions LLM, RAG, agentic systems.",
    }
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=make_claude_response(payload))
    role, cost = await classify_job_role(make_job(), client)
    assert role == JobRole.AI_ENGINEER
    assert cost > 0.0


@pytest.mark.asyncio
async def test_classify_job_role_identifies_software_engineer() -> None:
    payload = {
        "role": "software_engineer",
        "confidence": 0.88,
        "reasoning": "Backend API development, microservices.",
    }
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=make_claude_response(payload))
    role, cost = await classify_job_role(make_job(), client)
    assert role == JobRole.SOFTWARE_ENGINEER


@pytest.mark.asyncio
async def test_classify_job_role_identifies_data_science() -> None:
    payload = {
        "role": "data_science",
        "confidence": 0.91,
        "reasoning": "ML models, statistical analysis, experimentation.",
    }
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=make_claude_response(payload))
    role, cost = await classify_job_role(make_job(), client)
    assert role == JobRole.DATA_SCIENCE


@pytest.mark.asyncio
async def test_classify_job_role_identifies_not_relevant() -> None:
    payload = {
        "role": "not_relevant",
        "confidence": 0.99,
        "reasoning": "Mobile app development, iOS focus.",
    }
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=make_claude_response(payload))
    role, cost = await classify_job_role(make_job(), client)
    assert role == JobRole.NOT_RELEVANT


@pytest.mark.asyncio
async def test_classify_job_role_retries_on_json_parse_error() -> None:
    """JSON parse errors trigger retry (3 attempts), then raise."""
    message = MagicMock()
    message.content = [MagicMock(text="not valid json {{{")]
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=message)

    with pytest.raises(json.JSONDecodeError):
        await classify_job_role(make_job(), client)

    # Verify it retried 3 times (the default in _retry decorator)
    assert client.messages.create.call_count == 3


@pytest.mark.asyncio
async def test_classify_job_role_returns_not_relevant_on_invalid_role() -> None:
    payload = {
        "role": "invalid_role_xyz",
        "confidence": 0.50,
        "reasoning": "Unknown role.",
    }
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=make_claude_response(payload))
    role, cost = await classify_job_role(make_job(), client)
    assert role == JobRole.NOT_RELEVANT


# =============================================================================
# Tests for match_job (Two-stage filtering)
# =============================================================================


@pytest.mark.asyncio
async def test_skips_not_relevant_jobs() -> None:
    """Should classify job, find it not_relevant, and return None without matching."""
    classification_payload = {
        "role": "not_relevant",
        "confidence": 0.99,
        "reasoning": "Mobile app.",
    }
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=make_claude_response(classification_payload))
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert result is None
    # Should only call create once (classification), not twice
    assert client.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_matches_relevant_jobs() -> None:
    """Should classify job as relevant, then match against resumes."""
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM and agentic systems.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Strong Python and LLM experience.",
        "missing_keywords": ["MLOps"],
        "runner_up_filename": "software_engineer_ai.md",
        "runner_up_score": 0.72,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert isinstance(result, MatchResult)
    assert result.best_score == 0.85
    # Should call create twice (classification + matching)
    assert client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_returns_match_result_for_high_score() -> None:
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Strong Python and LLM experience.",
        "missing_keywords": ["MLOps"],
        "runner_up_filename": "software_engineer_ai.md",
        "runner_up_score": 0.72,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert isinstance(result, MatchResult)
    assert result.best_score == 0.85


@pytest.mark.asyncio
async def test_returns_match_result_when_score_below_threshold() -> None:
    classification_payload = {
        "role": "software_engineer",
        "confidence": 0.88,
        "reasoning": "Backend API.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.55,
        "match_reason": "Weak match.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert isinstance(result, MatchResult)
    assert result.best_score == 0.55


@pytest.mark.asyncio
async def test_selects_correct_resume_profile_by_filename() -> None:
    classification_payload = {
        "role": "software_engineer",
        "confidence": 0.88,
        "reasoning": "Backend systems.",
    }
    match_payload = {
        "best_resume_filename": "software_engineer_ai.md",
        "best_score": 0.80,
        "match_reason": "Good match.",
        "missing_keywords": [],
        "runner_up_filename": "ai_engineer.md",
        "runner_up_score": 0.65,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert result is not None
    assert result.best_resume.filename == "software_engineer_ai.md"
    assert result.runner_up_resume is not None
    assert result.runner_up_resume.filename == "ai_engineer.md"


@pytest.mark.asyncio
async def test_returns_none_on_match_json_parse_failure() -> None:
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    message = MagicMock()
    message.content = [MagicMock(text="not valid json {{{")]
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            message,
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert result is None


@pytest.mark.asyncio
async def test_missing_keywords_is_a_list_of_strings() -> None:
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.90,
        "match_reason": "Excellent fit.",
        "missing_keywords": ["Kubernetes", "Ray", "Triton"],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert result is not None
    assert result.missing_keywords == ["Kubernetes", "Ray", "Triton"]


@pytest.mark.asyncio
async def test_runner_up_is_none_when_only_one_resume() -> None:
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.80,
        "match_reason": "Only resume.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    single_resume = [make_resumes()[0]]
    result, cost = await match_job(make_job(), single_resume, client)
    assert result is not None
    assert result.runner_up_resume is None
    assert result.runner_up_score is None


@pytest.mark.asyncio
async def test_returns_none_when_filename_not_in_loaded_resumes() -> None:
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    match_payload = {
        "best_resume_filename": "nonexistent_resume.md",
        "best_score": 0.90,
        "match_reason": "Great match.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert result is None


@pytest.mark.asyncio
async def test_full_description_passed_not_snippet() -> None:
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Good fit.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
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
    await match_job(job, make_resumes(), client)
    # Second call should be the matching call, which should have full description
    call_kwargs = client.messages.create.call_args_list[1]
    user_message = next(
        m["content"] for m in call_kwargs.kwargs["messages"] if m["role"] == "user"
    )
    assert "FULL DESCRIPTION TEXT" in user_message
    assert "SHORT SNIPPET" not in user_message


@pytest.mark.asyncio
async def test_full_resume_content_passed_not_truncated() -> None:
    long_content = "x" * 5000
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Good fit.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    resumes = [
        ResumeProfile(
            role_label="AI Engineer",
            filename="ai_engineer.md",
            content=long_content,
        )
    ]
    await match_job(make_job(), resumes, client)
    # Second call should be the matching call
    call_kwargs = client.messages.create.call_args_list[1]
    user_message = next(
        m["content"] for m in call_kwargs.kwargs["messages"] if m["role"] == "user"
    )
    assert long_content in user_message


@pytest.mark.asyncio
async def test_role_specific_prompt_used_for_ai_engineer() -> None:
    """Verify that role-specific guidance is passed to Sonnet."""
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Good fit.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    await match_job(make_job(), make_resumes(), client)
    # Check second call (matching) has AI Engineer specific guidance
    call_kwargs = client.messages.create.call_args_list[1]
    system_prompt = call_kwargs.kwargs["system"]
    assert "RAG" in system_prompt
    assert "agentic ai" in system_prompt.lower()


@pytest.mark.asyncio
async def test_total_cost_includes_classification_and_matching() -> None:
    """Verify cost includes both Haiku (classification) and Sonnet (matching)."""
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    match_payload = {
        "best_resume_filename": "ai_engineer.md",
        "best_score": 0.85,
        "match_reason": "Good fit.",
        "missing_keywords": [],
        "runner_up_filename": None,
        "runner_up_score": None,
    }
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            make_claude_response(match_payload),
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert cost > 0.0
    # Should be approximately: (500 * HAIKU_INPUT + 100 * HAIKU_OUTPUT) + (500 * SONNET_INPUT + 100 * SONNET_OUTPUT)
    # HAIKU: 500 * 0.80 / 1M + 100 * 4.00 / 1M = 0.0008
    # SONNET: 500 * 3.00 / 1M + 100 * 15.00 / 1M = 0.003
    # Total: ~0.0038
    assert cost >= 0.001  # At least 0.001 (generous lower bound)


# ---------------------------------------------------------------------------
# test_classify_job_role_returns_default_on_empty_content_list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_job_role_returns_default_on_empty_content_list() -> None:
    """Test graceful handling when Anthropic SDK returns empty content list."""
    client = MagicMock()
    message = MagicMock()
    message.content = []  # Empty content list triggers IndexError
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    client.messages.create = AsyncMock(return_value=message)

    role, cost = await classify_job_role(make_job(), client)

    assert role == JobRole.NOT_RELEVANT


# ---------------------------------------------------------------------------
# test_match_job_returns_none_on_empty_content_list_in_match_stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_match_job_returns_none_on_empty_content_list_in_match_stage() -> None:
    """Test graceful handling when match stage gets empty content list."""
    classification_payload = {
        "role": "ai_engineer",
        "confidence": 0.95,
        "reasoning": "LLM systems.",
    }
    message = MagicMock()
    message.content = []  # Empty content list triggers IndexError
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            make_claude_response(classification_payload),
            message,
        ]
    )
    result, cost = await match_job(make_job(), make_resumes(), client)
    assert result is None
