import logging
from datetime import datetime, timezone

from supabase import Client
from tenacity import retry, stop_after_attempt, wait_exponential

from job_scout.models import JobPosting, MatchResult

logger = logging.getLogger(__name__)

_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)

SEEN_JOBS_TABLE = "seen_jobs"
SITE_HEALTH_TABLE = "site_health"


class JobStore:
    def __init__(self, client: Client) -> None:
        self._client = client

    @_retry
    def is_new(self, job: JobPosting) -> bool:
        result = (
            self._client.table(SEEN_JOBS_TABLE)
            .select("dedup_key")
            .eq("dedup_key", job.dedup_key)
            .execute()
        )
        return len(result.data) == 0

    @_retry
    def mark_seen(
        self,
        job: JobPosting,
        match_result: MatchResult | None = None,
    ) -> None:
        record: dict = {
            "dedup_key": job.dedup_key,
            "dedup_type": job.dedup_type,
            "title": job.title,
            "url": job.url,
            "company": job.company,
            "match_score": match_result.best_score if match_result else None,
            "seen_at": datetime.now(timezone.utc).isoformat(),
        }
        result = self._client.table(SEEN_JOBS_TABLE).upsert(record).execute()
        if not result.data:
            logger.error("mark_seen: upsert returned no data for dedup_key=%s", job.dedup_key)

    @_retry
    def update_site_health(self, site_name: str, job_count: int) -> int:
        current_zeros = self.get_consecutive_zeros(site_name)
        new_zeros = 0 if job_count > 0 else current_zeros + 1
        record: dict = {
            "site_name": site_name,
            "consecutive_zeros": new_zeros,
        }
        if job_count > 0:
            record["last_success_at"] = datetime.now(timezone.utc).isoformat()
        result = self._client.table(SITE_HEALTH_TABLE).upsert(record).execute()
        if not result.data:
            logger.error("update_site_health: upsert returned no data for site=%s", site_name)
        return new_zeros

    @_retry
    def get_last_run_at(self, site_name: str) -> datetime | None:
        result = (
            self._client.table(SITE_HEALTH_TABLE)
            .select("last_success_at")
            .eq("site_name", site_name)
            .execute()
        )
        if not result.data or result.data[0]["last_success_at"] is None:
            return None
        raw = result.data[0]["last_success_at"]
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @_retry
    def get_consecutive_zeros(self, site_name: str) -> int:
        result = (
            self._client.table(SITE_HEALTH_TABLE)
            .select("consecutive_zeros")
            .eq("site_name", site_name)
            .execute()
        )
        if not result.data:
            return 0
        return result.data[0]["consecutive_zeros"]
