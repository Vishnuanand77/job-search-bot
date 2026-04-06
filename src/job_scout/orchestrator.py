import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import anthropic
import httpx
from supabase import create_client

from job_scout.config import AppConfig, load_config
from job_scout.dedup.store import JobStore
from job_scout.extractor.claude_extractor import extract_jobs
from job_scout.matcher.claude_matcher import match_job
from job_scout.models import MatchResult, RunSummary, SiteResult, SiteTarget
from job_scout.notifier.telegram import send_digest, send_failure_alert
from job_scout.scraper.dispatcher import ScrapingFailedError, fetch_site_content

logger = logging.getLogger(__name__)

CONCURRENCY_LIMIT = 3


async def _process_site(
    target: SiteTarget,
    config: AppConfig,
    anthropic_client: anthropic.Anthropic,
    store: JobStore,
    http_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> SiteResult:
    async with semaphore:
        try:
            try:
                text, tier_used = await fetch_site_content(target, http_client)
            except ScrapingFailedError as exc:
                logger.warning("[%s] scraping failed: %s", target.name, exc)
                store.update_site_health(target.name, 0)
                return SiteResult(
                    site_name=target.name,
                    url=target.url,
                    jobs_found=0,
                    new_jobs=0,
                    matches=[],
                    error=str(exc),
                    scraper_tier_used="none",
                )

            jobs, extract_cost = await extract_jobs(text, target.name, target.url, anthropic_client)
            store.update_site_health(target.name, len(jobs))

            new_jobs: int = 0
            site_cost: float = extract_cost
            site_matches: list[MatchResult] = []

            for job in jobs:
                if not store.is_new(job):
                    continue
                new_jobs += 1
                result, match_cost = await match_job(job, config.resumes, anthropic_client, config.match_threshold)
                site_cost += match_cost
                store.mark_seen(job, match_result=result)
                if result is not None:
                    site_matches.append(result)

            logger.info(
                "[%s] tier=%s jobs=%d new=%d matches=%d",
                target.name,
                tier_used,
                len(jobs),
                new_jobs,
                len(site_matches),
            )

            return SiteResult(
                site_name=target.name,
                url=target.url,
                jobs_found=len(jobs),
                new_jobs=new_jobs,
                matches=site_matches,
                error=None,
                scraper_tier_used=tier_used,
                cost_usd=site_cost,
            )

        except Exception as exc:
            logger.error("[%s] unexpected error: %s", target.name, exc)
            await send_failure_alert(
                error=exc,
                context=f"processing {target.name}",
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
            )
            store.update_site_health(target.name, 0)
            return SiteResult(
                site_name=target.name,
                url=target.url,
                jobs_found=0,
                new_jobs=0,
                matches=[],
                error=str(exc),
                scraper_tier_used="none",
            )


async def run(config: AppConfig) -> RunSummary:
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    supabase_client = create_client(config.supabase_url, config.supabase_key)
    store = JobStore(supabase_client)
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        tasks = [
            _process_site(target, config, anthropic_client, store, http_client, semaphore)
            for target in config.targets
        ]
        results: list[SiteResult] = await asyncio.gather(*tasks)

    all_matches: list[MatchResult] = []
    errors: list[str] = []
    total_jobs = 0
    total_new = 0
    total_cost: float = 0.0

    for r in results:
        total_jobs += r.jobs_found
        total_new += r.new_jobs
        total_cost += r.cost_usd
        all_matches.extend(r.matches)
        if r.error:
            errors.append(f"{r.site_name} — {r.error}")

    sites_failed = sum(1 for r in results if r.error)
    sites_succeeded = len(results) - sites_failed

    stale_sites = {
        r.site_name: store.get_consecutive_zeros(r.site_name)
        for r in results
        if store.get_consecutive_zeros(r.site_name) >= 3
    }

    summary = RunSummary(
        run_at=datetime.now(timezone.utc),
        sites_attempted=len(results),
        sites_succeeded=sites_succeeded,
        sites_failed=sites_failed,
        total_jobs_found=total_jobs,
        new_jobs=total_new,
        matches=all_matches,
        errors=errors,
        total_cost_usd=total_cost,
    )

    await send_digest(
        summary,
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        dry_run=config.dry_run,
        stale_sites=stale_sites or None,
    )

    return summary


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    try:
        config = load_config()
        summary = asyncio.run(run(config))
        sys.exit(0 if summary.sites_failed == 0 else 1)
    except Exception as exc:
        asyncio.run(
            send_failure_alert(
                error=exc,
                context="orchestrator startup",
                bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
                chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            )
        )
        raise


if __name__ == "__main__":
    main()
