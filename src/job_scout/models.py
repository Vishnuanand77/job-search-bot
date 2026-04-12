from dataclasses import dataclass, field
from datetime import date, datetime, time
from hashlib import sha256


@dataclass
class SiteTarget:
    name: str
    url: str
    scrape_tier: str  # 'http' or 'playwright'
    pagination_param: str | None = None  # query param name, e.g. "start"
    pagination_step: int = 20            # increment per page
    max_pages: int = 5                   # hard ceiling on pages fetched


@dataclass
class JobPosting:
    title: str
    url: str
    company: str
    description: str
    snippet: str
    job_id: str | None
    posted_date: date | None
    posted_time: time | None = None  # hour-level precision; scraped from <time datetime> or JSON-LD
    location: str | None = None
    dedup_key: str = field(init=False)
    dedup_type: str = field(init=False)

    def __post_init__(self) -> None:
        if self.job_id:
            self.dedup_key = self.job_id
            self.dedup_type = "job_id"
        else:
            self.dedup_key = sha256(self.url.encode()).hexdigest()[:16]
            self.dedup_type = "url_hash"


@dataclass
class ResumeProfile:
    role_label: str
    filename: str
    content: str


@dataclass
class MatchResult:
    job: JobPosting
    best_resume: ResumeProfile
    best_score: float
    match_reason: str
    missing_keywords: list[str]
    runner_up_resume: ResumeProfile | None
    runner_up_score: float | None


@dataclass
class SiteResult:
    site_name: str
    url: str
    jobs_found: int
    new_jobs: int
    matches: list[MatchResult]
    error: str | None
    scraper_tier_used: str
    cost_usd: float = 0.0
    consecutive_zeros: int = 0


@dataclass
class RunSummary:
    run_at: datetime
    sites_attempted: int
    sites_succeeded: int
    sites_failed: int
    total_jobs_found: int
    new_jobs: int
    matches: list[MatchResult]
    errors: list[str]
    total_cost_usd: float = 0.0
