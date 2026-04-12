import asyncio
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import anthropic
from playwright.async_api import async_playwright
from supabase import create_client

from job_scout.config import AppConfig, load_config
from job_scout.dedup.store import JobStore
from job_scout.extractor.claude_extractor import extract_jobs
from job_scout.matcher.claude_matcher import match_job
from job_scout.models import JobPosting, MatchResult, RunSummary, SiteResult, SiteTarget
from job_scout.notifier.telegram import send_digest, send_failure_alert
from job_scout.scraper.dispatcher import ScrapingFailedError, fetch_site_content
from job_scout.scraper.http_scraper import BROWSER_HEADERS

logger = logging.getLogger(__name__)

CONCURRENCY_LIMIT = 3


def _build_page_url(base_url: str, param: str, offset: int) -> str:
    parsed = urlparse(base_url)
    params = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    params[param] = str(offset)
    return urlunparse(parsed._replace(query=urlencode(params)))


def _detect_stop(
    jobs: list[JobPosting],
    last_run_at: datetime | None,
    new_job_count: int,
) -> bool:
    if not jobs:
        return True
    if last_run_at is None:
        return False

    has_time = any(j.posted_time is not None for j in jobs)
    has_date = any(j.posted_date is not None for j in jobs)

    if has_time and has_date:
        # Mixed case: some jobs have date+time, some may have only date.
        # Check both types with appropriate thresholds.
        timed_jobs = [j for j in jobs if j.posted_date and j.posted_time]
        dated_only_jobs = [j for j in jobs if j.posted_date and not j.posted_time]

        # All timed jobs must be older than last_run_at
        all_timed_old = all(
            datetime.combine(j.posted_date, j.posted_time, tzinfo=timezone.utc) < last_run_at
            for j in timed_jobs
        ) if timed_jobs else True

        # All dated-only jobs must be older than 1 day before last_run_at
        cutoff_date = (last_run_at - timedelta(days=1)).date()
        all_dated_old = all(
            j.posted_date < cutoff_date
            for j in dated_only_jobs
        ) if dated_only_jobs else True

        return all_timed_old and all_dated_old

    if has_date:
        cutoff_date = (last_run_at - timedelta(days=1)).date()
        dated_jobs = [j for j in jobs if j.posted_date]
        return all(j.posted_date < cutoff_date for j in dated_jobs)

    return new_job_count == 0


async def _process_site(
    target: SiteTarget,
    config: AppConfig,
    anthropic_client: anthropic.AsyncAnthropic,
    store: JobStore,
    semaphore: asyncio.Semaphore,
) -> SiteResult:
    async with semaphore:
        all_jobs_found: int = 0
        new_jobs: int = 0
        site_cost: float = 0.0
        site_matches: list[MatchResult] = []
        tier_used: str = "none"

        last_run_at = store.get_last_run_at(target.name)
        pages = range(target.max_pages) if target.pagination_param else range(1)

        try:
            # Create browser once per site, reuse context across pages
            async with async_playwright() as pw:
                async with await pw.chromium.launch(headless=True) as browser:
                    context = await browser.new_context(
                        user_agent=BROWSER_HEADERS["User-Agent"]
                    )

                    try:
                        for page_num in pages:
                            if target.pagination_param:
                                page_url = _build_page_url(
                                    target.url,
                                    target.pagination_param,
                                    page_num * target.pagination_step,
                                )
                            else:
                                page_url = target.url

                            page_target = SiteTarget(
                                name=target.name,
                                url=page_url,
                                scrape_tier=target.scrape_tier,
                            )

                            try:
                                text, tier_used = await fetch_site_content(page_target, context)
                            except ScrapingFailedError as exc:
                                logger.warning("[%s] page=%d scraping failed: %s", target.name, page_num, exc)
                                if page_num == 0:
                                    new_zeros = store.update_site_health(target.name, 0)
                                    return SiteResult(
                                        site_name=target.name,
                                        url=target.url,
                                        jobs_found=0,
                                        new_jobs=0,
                                        matches=[],
                                        error=str(exc),
                                        scraper_tier_used="none",
                                        consecutive_zeros=new_zeros,
                                    )
                                break

                            jobs, extract_cost = await extract_jobs(text, target.name, page_url, anthropic_client)
                            site_cost += extract_cost
                            all_jobs_found += len(jobs)

                            page_new: int = 0
                            for job in jobs:
                                if not store.is_new(job):
                                    continue
                                page_new += 1
                                new_jobs += 1
                                result, match_cost = await match_job(job, config.resumes, anthropic_client)
                                site_cost += match_cost
                                store.mark_seen(job, match_result=result)
                                if result is not None and result.best_score >= config.match_threshold:
                                    site_matches.append(result)

                            logger.info(
                                "[%s] page=%d tier=%s jobs=%d new=%d matches=%d",
                                target.name,
                                page_num,
                                tier_used,
                                len(jobs),
                                page_new,
                                len(site_matches),
                            )

                            if _detect_stop(jobs, last_run_at, page_new):
                                break

                            # Jitter between paginated requests to same domain (1-3s)
                            # Skip on last page to avoid unnecessary delay after final page
                            if page_num < target.max_pages - 1 and target.pagination_param:
                                await asyncio.sleep(random.uniform(1, 3))
                    finally:
                        await context.close()

            new_zeros = store.update_site_health(target.name, all_jobs_found)

            return SiteResult(
                site_name=target.name,
                url=target.url,
                jobs_found=all_jobs_found,
                new_jobs=new_jobs,
                matches=site_matches,
                error=None,
                scraper_tier_used=tier_used,
                cost_usd=site_cost,
                consecutive_zeros=new_zeros,
            )

        except Exception as exc:
            logger.error("[%s] unexpected error: %s", target.name, exc)
            # Per-site errors are collected and reported in the digest footer,
            # not sent as immediate alerts (prevents alert flooding).
            # Pass actual all_jobs_found: if extraction succeeded but matching failed,
            # we should not mark the site as having zero jobs (which increments
            # consecutive_zeros incorrectly).
            new_zeros = store.update_site_health(target.name, all_jobs_found)
            return SiteResult(
                site_name=target.name,
                url=target.url,
                jobs_found=all_jobs_found,
                new_jobs=new_jobs,
                matches=site_matches,
                error=str(exc),
                scraper_tier_used=tier_used,
                consecutive_zeros=new_zeros,
            )


async def run(config: AppConfig) -> RunSummary:
    anthropic_client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
    supabase_client = create_client(config.supabase_url, config.supabase_key)
    store = JobStore(supabase_client)
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    tasks = [
        _process_site(target, config, anthropic_client, store, semaphore)
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

    stale_sites = {r.site_name: r.consecutive_zeros for r in results if r.consecutive_zeros >= 3}

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
