import json
import logging
from datetime import date
from urllib.parse import urljoin, urlparse

import anthropic

from job_scout.models import JobPosting

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096
MAX_JOBS = 50

SYSTEM_PROMPT = """\
You are a job listing extractor. You receive the text content of a company
careers page. Extract all visible job listings.

Return ONLY valid JSON — no preamble, no explanation, no markdown fences:
{
  "jobs": [
    {
      "title": "string",
      "url": "string — absolute URL; construct from base if relative",
      "job_id": "string or null — numeric/alphanumeric ID from URL or page",
      "description": "string — complete full text of the job description",
      "snippet": "string — 2-3 sentence summary of what this role does",
      "posted_date": "YYYY-MM-DD or null",
      "location": "string or null"
    }
  ]
}

Rules:
- Return {"jobs": []} if no listings are visible
- Never invent jobs — only extract what is explicitly listed
- description must be the full responsibilities and requirements text
- Convert relative dates to absolute using today's date
- Return only JSON\
"""


async def extract_jobs(
    content: str,
    company_name: str,
    site_url: str,
    client: anthropic.Anthropic,
) -> list[JobPosting]:
    if not content:
        return []

    user_message = f"Company: {company_name}\nSite URL: {site_url}\n\n{content}"

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse failure extracting jobs for %s: %s", company_name, exc)
        return []

    raw_jobs: list[dict] = data.get("jobs", [])

    if len(raw_jobs) > MAX_JOBS:
        logger.warning(
            "Extracted %d jobs for %s — capping at %d",
            len(raw_jobs),
            company_name,
            MAX_JOBS,
        )
        raw_jobs = raw_jobs[:MAX_JOBS]

    postings: list[JobPosting] = []
    for job in raw_jobs:
        url = _resolve_url(job.get("url", ""), site_url)
        posted_date = _parse_date(job.get("posted_date"))
        postings.append(
            JobPosting(
                title=job.get("title", ""),
                url=url,
                company=company_name,
                description=job.get("description", ""),
                snippet=job.get("snippet", ""),
                job_id=job.get("job_id") or None,
                posted_date=posted_date,
                location=job.get("location"),
            )
        )

    return postings


def _resolve_url(url: str, base_url: str) -> str:
    if not url:
        return base_url
    parsed = urlparse(url)
    if parsed.scheme:
        return url
    return urljoin(base_url, url)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
