import json
import logging

import anthropic

from job_scout.models import JobPosting, MatchResult, ResumeProfile

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048

# Pricing per token (USD) — verify at https://anthropic.com/pricing
SONNET_INPUT_COST_PER_TOKEN = 3.00 / 1_000_000
SONNET_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000

SYSTEM_PROMPT = """\
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

Scoring: 0.9+ exceptional · 0.75–0.9 strong · 0.6–0.75 moderate · <0.6 weak
missing_keywords: up to 8 important technical skills/tools explicitly required \
but absent from the best resume. Only genuinely important gaps.\
"""


async def match_job(
    job: JobPosting,
    resumes: list[ResumeProfile],
    client: anthropic.AsyncAnthropic,
) -> tuple[MatchResult | None, float]:
    resume_index = {r.filename: r for r in resumes}

    resume_sections = "\n\n".join(
        f"--- Resume: {r.filename} ({r.role_label}) ---\n{r.content}"
        for r in resumes
    )
    user_message = (
        f"--- Job Description ---\n{job.description}\n\n{resume_sections}"
    )

    cost = 0.0
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        cost = (
            response.usage.input_tokens * SONNET_INPUT_COST_PER_TOKEN
            + response.usage.output_tokens * SONNET_OUTPUT_COST_PER_TOKEN
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("match_job: failed to parse Claude response: %s", exc)
        return None, cost

    best_filename: str = data.get("best_resume_filename", "")
    best_resume = resume_index.get(best_filename)
    if best_resume is None:
        logger.warning(
            "match_job: best_resume_filename '%s' not found in loaded resumes",
            best_filename,
        )
        return None, cost

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
    ), cost
