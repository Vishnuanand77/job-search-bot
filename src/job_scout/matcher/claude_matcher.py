import json
import logging
from enum import Enum

import anthropic

from job_scout.models import JobPosting, MatchResult, ResumeProfile

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-4-6"
HAIKU_MAX_TOKENS = 256
SONNET_MAX_TOKENS = 2048

# Pricing per token (USD) — verify at https://anthropic.com/pricing
HAIKU_INPUT_COST_PER_TOKEN = 0.80 / 1_000_000
HAIKU_OUTPUT_COST_PER_TOKEN = 4.00 / 1_000_000
SONNET_INPUT_COST_PER_TOKEN = 3.00 / 1_000_000
SONNET_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000


class JobRole(str, Enum):
    """Job role classification."""
    SOFTWARE_ENGINEER = "software_engineer"
    DATA_SCIENCE = "data_science"
    AI_ENGINEER = "ai_engineer"
    NOT_RELEVANT = "not_relevant"


ROLE_CLASSIFIER_PROMPT = """\
You are an expert technical recruiter classifying job postings.

Classify this job posting into ONE of these categories:
- "software_engineer": Backend/frontend systems, APIs, infrastructure, databases
- "data_science": Predictive models, statistical analysis, experimentation, analytics
- "ai_engineer": LLMs, RAG, agentic AI, ML pipelines, AI systems end-to-end
- "not_relevant": Roles in DevOps, mobile (iOS/Android), embedded systems, sales, non-technical

Return ONLY valid JSON:
{
  "role": "software_engineer|data_science|ai_engineer|not_relevant",
  "confidence": 0.95,
  "reasoning": "one sentence explaining the classification"
}
"""


def _get_match_system_prompt(role: JobRole) -> str:
    """Build conditional system prompt based on job role."""
    base = """\
You are an expert technical recruiter evaluating resume-to-job fit.
You will receive a complete job description and multiple resumes.

Tasks:
1. Identify which resume is the strongest fit for this role
2. Score that fit 0.0 to 1.0
3. Score the second-best resume
4. List keywords in the JD absent from the best-fit resume

Return ONLY valid JSON — no preamble:
{
  "best_resume_filename": "string",
  "best_score": 0.85,
  "match_reason": "string — one concise sentence",
  "missing_keywords": ["keyword1", "keyword2"],
  "runner_up_filename": "string or null",
  "runner_up_score": 0.72
}

SCORING RUBRIC:
"""

    role_guidance = {
        JobRole.SOFTWARE_ENGINEER: """\
0.9+: Resume has Python/Java + FastAPI/Spring Boot/Node.js, 70%+ core tech stack (APIs, databases, \
cloud), seniority matches entry-to-mid-career. OR demonstrates full-stack systems thinking.

0.8-0.89: Resume has Python + one framework, 60-69% of requirements, entry or early mid-career level. \
OR can ramp on missing core tools in 2-3 weeks.

0.7-0.79: Resume has Python but missing major framework/cloud platform. 50-59% of requirements. \
Entry-level only. Would need 4+ weeks to ramp.

<0.7: Job requires Go, Rust, C++, or deep DevOps/Kubernetes administration. OR seniority mismatch \
(senior principal, internship level).
""",
        JobRole.DATA_SCIENCE: """\
0.9+: Resume has Python + ML frameworks (XGBoost, TensorFlow, Scikit-learn) + statistical rigor. \
70%+ of explicit requirements (modeling, evaluation, experimentation). Seniority: entry-to-mid-career. \
Shows production ML or A/B testing experience.

0.8-0.89: Resume has Python + ML experience, 60-69% of requirements. Entry or early mid-career. \
May have BI/analytics instead of predictive modeling, but fundamentals are strong.

0.7-0.79: Resume has Python + some analytics/statistics. 50-59% of requirements. Entry-level only. \
Would need 4+ weeks to ramp on production ML workflows.

<0.7: Job requires Go, Rust, or deep domain (medical research, physics). Seniority mismatch.
""",
        JobRole.AI_ENGINEER: """\
0.9+: Resume has shipped production GenAI/LLM/RAG systems end-to-end (prompting, evaluation, \
deployment). Python + FastAPI/frameworks. 75%+ of requirements. Seniority: entry-to-mid-career. \
Demonstrates agentic AI or RAG pipeline experience.

0.8-0.89: Resume has Python + LangChain/RAG experience OR strong ML + product thinking. 65-74% of \
requirements. Entry or early mid-career. Can ramp on LLM-specific tools in 1-2 weeks.

0.7-0.79: Resume has Python + ML frameworks but no LLM/GenAI shipped experience. 55-64% of \
requirements. Entry-level only. Would need 2-3 weeks to ramp on GenAI specifics.

<0.7: Job requires Go, Rust, C++, or deep research-level AI. Seniority mismatch.
""",
        JobRole.NOT_RELEVANT: "0.0: This job is not Software Engineering, Data Science, or AI Engineering.",
    }

    return base + role_guidance.get(role, "")


async def classify_job_role(
    job: JobPosting,
    client: anthropic.AsyncAnthropic,
) -> tuple[JobRole, float]:
    """Classify job into Software Engineering, Data Science, AI Engineering, or Not Relevant.

    Returns: (role, cost_usd)
    """
    user_message = f"--- Job Title ---\n{job.title}\n\n--- Job Description ---\n{job.description}"

    cost = 0.0
    try:
        response = await client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=HAIKU_MAX_TOKENS,
            system=ROLE_CLASSIFIER_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        cost = (
            response.usage.input_tokens * HAIKU_INPUT_COST_PER_TOKEN
            + response.usage.output_tokens * HAIKU_OUTPUT_COST_PER_TOKEN
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        role_str = data.get("role", "not_relevant").lower()
        role = JobRole(role_str) if role_str in [r.value for r in JobRole] else JobRole.NOT_RELEVANT
        logger.debug(
            "classify_job_role: job=%s title=%s role=%s confidence=%.2f",
            job.job_id or job.dedup_key,
            job.title,
            role.value,
            data.get("confidence", 0.0),
        )
        return role, cost
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("classify_job_role: failed to parse or validate role classification: %s", exc)
        return JobRole.NOT_RELEVANT, cost


async def match_job(
    job: JobPosting,
    resumes: list[ResumeProfile],
    client: anthropic.AsyncAnthropic,
) -> tuple[MatchResult | None, float]:
    """Evaluate job posting against all resumes with role-specific scoring.

    Stage 1: Classify job role (Haiku)
    Stage 2: If relevant, match against resumes with role-specific rubric (Sonnet)

    Returns: (match_result, total_cost_usd)
    """
    # Stage 1: Classify job role
    role, classification_cost = await classify_job_role(job, client)
    total_cost = classification_cost

    if role == JobRole.NOT_RELEVANT:
        logger.debug("match_job: skipping not_relevant job=%s", job.job_id or job.dedup_key)
        return None, total_cost

    # Stage 2: Match resumes for relevant jobs
    resume_index = {r.filename: r for r in resumes}

    resume_sections = "\n\n".join(
        f"--- Resume: {r.filename} ({r.role_label}) ---\n{r.content}"
        for r in resumes
    )

    user_message = (
        f"--- Job Title ---\n{job.title}\n\n--- Job Description ---\n{job.description}\n\n{resume_sections}"
    )

    system_prompt = _get_match_system_prompt(role)

    try:
        response = await client.messages.create(
            model=SONNET_MODEL,
            max_tokens=SONNET_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        match_cost = (
            response.usage.input_tokens * SONNET_INPUT_COST_PER_TOKEN
            + response.usage.output_tokens * SONNET_OUTPUT_COST_PER_TOKEN
        )
        total_cost += match_cost

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("match_job: failed to parse Claude response: %s", exc)
        return None, total_cost

    best_filename: str = data.get("best_resume_filename", "")
    best_resume = resume_index.get(best_filename)
    if best_resume is None:
        logger.warning(
            "match_job: best_resume_filename '%s' not found in loaded resumes",
            best_filename,
        )
        return None, total_cost

    best_score: float = float(data.get("best_score", 0.0))

    runner_up_filename: str | None = data.get("runner_up_filename")
    runner_up_resume = resume_index.get(runner_up_filename) if runner_up_filename else None
    runner_up_score_raw = data.get("runner_up_score")
    runner_up_score = float(runner_up_score_raw) if runner_up_score_raw is not None else None

    return MatchResult(
        job=job,
        best_resume=best_resume,
        best_score=best_score,
        match_reason=data.get("match_reason", ""),
        missing_keywords=data.get("missing_keywords", []),
        runner_up_resume=runner_up_resume,
        runner_up_score=runner_up_score,
    ), total_cost
