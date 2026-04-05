from dataclasses import dataclass, field
from datetime import date, datetime
from hashlib import sha256


@dataclass
class SiteTarget:
    name: str
    url: str
    scrape_tier: str  # 'http' or 'playwright'


@dataclass
class JobPosting:
    title: str
    url: str
    company: str
    description: str
    snippet: str
    job_id: str | None
    posted_date: date | None
    location: str | None
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
