from __future__ import annotations
import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.association import JobKeywordLink
from app.models.job import Job, JobStatus
from app.models.keyword import SearchKeyword
from app.scrapers.base import BaseScraper, JobSummary
from app.services.ai_analyzer import AIAnalyzer



logger = logging.getLogger(__name__)


FAILED_OUTCOMES = {
    "no_scraper",
    "fetch_failed",
    "ai_failed",
    "failed",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc). replace(tzinfo=None)


@dataclass
class DiscoveryStats:
    pages_fetched: int = 0
    summaries_seen: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    links_added:  int = 0
    errors: int = 0


@dataclass
class EnrichmentStats:
    jobs_found: int = 0 
    enriched: int = 0
    unchanged: int = 0
    failed: int = 0


class ScraperManager:
    def __init__(
            self, 
            scrapers: List[BaseScraper],
            ai_analyzer: AIAnalyzer,
    ) -> None:
        self.scrapers: Dict[str, BaseScraper] = {
            scraper.source_name: scraper for scraper in scrapers
        }
        self.ai_analyzer = ai_analyzer
    
    # Discovery
    async def run_discover(
            self,
            keywords: List[str],
            location: str,
            session: AsyncSession,
    ) -> DiscoveryStats:
        total_stats = DiscoveryStats()

        page_size = settings.SCRAPER_PAGE_SIZE
        max_pages = settings.SCRAPER_MAX_PAGES

        for scraper in self.scrapers.values():
            for raw_keyword in keywords:
                keyword = raw_keyword.strip()

                if not keyword:
                    continue

                stats = DiscoveryStats()

                logger.info(
                    "Discovery started: platform='%s' keyword='%s' location='%s'",
                    scraper.source_name,
                    keyword,
                    location,
                )

                try:
                    keyword_row = await self._get_or_create_keyword(
                        keyword,
                        session,
                    )

                    page = 1

                    while page <= max_pages:
                        summaries = await scraper.discover(
                            keyword,
                            location,
                            page,
                            page_size=page_size,
                        )

                        if not summaries:
                            break

                        stats.summaries_seen += len(summaries)

                        for summary in summaries:
                            created, link_created = await self._upsert_summary(
                                platform=scraper.source_name,
                                summary=summary,
                                keyword_id=keyword_row.id,
                                session=session,
                            )

                            if created:
                                stats.jobs_created += 1
                            else:
                                stats.jobs_updated += 1
                            
                            if link_created:
                                stats.links_added += 1
                        await session.commit()
                        stats.pages_fetched += 1

                        if len(summaries) < page_size:
                            break
                        page += 1
                    else:
                        logger.warning(
                            "Discovery stopped at max_pages=%d for keyword='%s' platform='%s'",
                            max_pages,
                            keyword,
                            scraper.source_name,
                        )
                    
                    keyword_row.last_scraped_at = _utcnow()
                    session.add(keyword_row)
                    await session.commit()

                    logger.info(
                        "Discovery finished: platform='%s' keyword='%s' pages=%d summaries=%d created=%d updated=%d links=%d",
                        scraper.source_name,
                        keyword,
                        stats.pages_fetched,
                        stats.summaries_seen,
                        stats.jobs_created,
                        stats.jobs_updated,
                        stats.links_added,
                    )

                except Exception:
                    logger.exception(
                        "Discovery failed: platform='%s' keyword='%s'",
                        scraper.source_name,
                        keyword,
                    )
                    stats.errors += 1
                    await session.rollback()
                
                finally:
                    total_stats.pages_fetched += stats.pages_fetched
                    total_stats.summaries_seen += stats.summaries_seen
                    total_stats.jobs_created += stats.jobs_created
                    total_stats.jobs_updated += stats.jobs_updated
                    total_stats.links_added += stats.links_added
                    total_stats.errors += stats.errors

        return total_stats
    
    async def _get_or_create_keyword(
            self,
            keyword: str,
            session: AsyncSession,
    ) -> SearchKeyword:
        insert_stmt = (
            pg_insert(SearchKeyword)
            .values(keyword=keyword)
            .on_conflict_do_nothing(index_elements=["keyword"])
        )
        await session.execute(insert_stmt)

        result = await session.execute(
            select(ScraperManager).where(SearchKeyword.keyword == keyword)
        )
        return result.scalar_one()
    
    async def _upsert_summary(
            self,
            platform: str,
            summary: JobSummary,
            keyword_id: int,
            session: AsyncSession,
    ) -> Tuple[bool, bool]:
        result = await session.execute(
            select(Job).where(
                Job.platform == platform,
                Job.platform_job_id == summary.platform_job_id,
            )
        )
        job: Optional[Job] = result.scalar_one_or_none()

        if job is None:
            insert_stmt = (
                pg_insert(Job)
                .values(
                    platform=platform,
                    platform_job_id=summary.platform_job_id,
                    title=summary.title,
                    description="",
                    company_name="",
                    location=summary.location,
                    external_activated_at=summary.external_activated_at,
                    expires_at=summary.expires_at,
                    is_expired=summary.is_expired,
                    last_seen_at=_utcnow(),
                    status=JobStatus.PENDING_DETAIL,
                )
                .on_conflict_do_nothing(constraint="uq_job_platform_id")
                .returning(Job.id)
            )

            result = await session.execute(insert_stmt)
            inserted_id = result.scalar_one_or_none()

            if inserted_id is None:
                result = await session.execute(
                    select(Job.id).where(
                        Job.platform == platform,
                        Job.platform_job_id == summary.platform_job_id,
                    )
                )
                job_id = result.scalar_one()
                created = False
            else:
                job_id = inserted_id
                created = True
        else:
            job_id = job.id
            created = False

            previous_activation = job.external_activated_at

            job.last_seen_at = _utcnow()
            job.is_expired = summary.is_expired
            job.expires_at = summary.expires_at

            activation_changed = summary.external_activated_at != previous_activation

            if activation_changed and job.status in (
                JobStatus.ENRICHED,
                JobStatus.FAILED,
                JobStatus.NEEDS_RECHECK,
            ):
                job.status = JobStatus.NEEDS_RECHECK
            
            job.external_activated_at = summary.external_activated_at
            session.add(job)
        
        link_stmt = (
            pg_insert(JobKeywordLink)
            .values(job_id=job_id, keyword_id=keyword_id)
            .on_conflict_do_nothing()
        )
        link_result = await session.execute(link_stmt)
        link_created = (link_result.rowcount or 0) > 0

        return created, link_created
    

    # Enrichment

    async def run_enrichment(
            self,
            session: AsyncSession,
            concurrency: Optional[int] = None,
            batch_size: Optional[int] = None,
    ) -> EnrichmentStats:
        
        effective_concurrency = max(
            1,
            concurrency or settings.ENRICHMENT_CONCURRENCY,
        )

        effective_batch_size = max(
            1,
            batch_size or settings.ENRICHMENT_BATCH_SIZE,
        )

        jobs = await self._get_jobs_needing_enrichment(
            session,
            effective_batch_size
        )

        stats = EnrichmentStats(jobs_found=len(jobs))

        logger.info(
            "Enrichment started: found=%d concurrency=%d batch_size=%d",
            stats.jobs_found,
            effective_concurrency,
            effective_batch_size,
        )

        if not jobs:
            return stats
        
        semaphore = asyncio.Semaphore(effective_concurrency)

        results = await asyncio.gather(
            *(self._enrich_network_only(job, semaphore) for job in jobs),
            return_exceptions=True,
        )

        for job, result in zip(jobs, results):
            if isinstance(result, BaseException):
                logger.error(
                    "Unexpected enrichment task failed for job_id=%s: %s",
                    job.platform_job_id,
                    result,
                    exc_info=result,
                )
                result = {"outcome": "failed"}
            
            if not isinstance(result, dict):
                result = {"outcome": "failed"}
            
            outcome = result.get("outcome", "failed")

            try:
                await self._apply_enrichment_result(job, result, session)
            except Exception:
                logger.exception(
                    "Failed to apply enrichment result for job_id=%s",
                    job.platform_job_id,
                )
                await session.rollback()
                stats.failed += 1
                continue

            if outcome == "enriched":
                stats.enriched += 1
            elif outcome == "unchanged":
                stats.unchanged +=1
            else:
                stats.failed +=1
        
        logger.info(
            "Enrichment finished: found=%d enriched=%d unchanged=%d failed=%d",
            stats.jobs_found,
            stats.enriched,
            stats.unchanged,
            stats.failed,
        )
        
        return stats
    
    async def _get_jobs_needing_enrichment(
            self,
            session: AsyncSession,
            batch_size: int,
    ) -> List[Job]:
        
        stmt = (
            select(Job)
            .where(
                Job.status.in_(
                    [
                        JobStatus.PENDING_DETAIL,
                        JobStatus.NEEDS_RECHECK,
                    ]
                )
            )
            .order_by(Job.last_seen_at.desc())
            .limit(batch_size)
        )
        
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    async def _enrich_network_only(
            self,
            job: Job,
            semaphore: asyncio.Semaphore,
    ) -> Dict[str, Any]:
        async with semaphore:
            scraper = self.scrapers.get(job.platform)

            if scraper is None:
                logger.error(
                    "No scraper registered for platform '%s'",
                    job.platform,
                )
                return {"outcome": "no_scraper"}
            
            try:
                detail = await scraper.fetch_detail(job.platform_job_id)
            except Exception:
                logger.exception(
                    "Unexpected fetch_detail error for job_id=%s",
                    job.platform_job_id,
                )
                return {"outcome": "fetch_failed"}
            
            if detail is None:
                return {"outcome": "fetch_failed"}
            
            new_hash = self._comute_content_hash(
                detail.title,
                detail.description,
                detail.salary,
            )

            if (
                job.status == JobStatus.NEEDS_RECHECK
                and new_hash == job.content_hash
            ):
                return {
                    "outcome": "unchanged",
                    "detail": detail,
                    "content_hash": new_hash,
                }
            
            try:
                extracted = await self.ai_analyzer.extract_structured(
                    detail.description
                )
                vector = await self.ai_analyzer.embed_skills(
                    extracted.get("tools_and_technologies", [])
                )
            except Exception:
                logger.exception(
                    "AI pipeline failed for job_id=%s",
                    job.platform_job_id,
                )
                return {"outcome": "ai_failed"}
            
            return {
                "outcome": "enriched",
                "detail": detail,
                "extracted": extracted,
                "vector": vector,
                "content_hash": new_hash,
            }

        async def _apply_enrichment_result(
                self,
                job: Job,
                result: Dict[str, Any],
                session: AsyncSession,
        ) -> None:
            outcome = result.get("outcome", "failed")   

            if outcome in FAILED_OUTCOMES:
                job.status = JobStatus.FAILED
                session.add(job)
                await session.commit()

                logger.warning(
                    "Enrichment failed for job_id=%s outcome=%s",
                    job.platform_job_id,
                    outcome,
                )
                return
            
            if outcome == "unchanged":
                job.status = JobStatus.ENRICHED
                job.scraped_at = _utcnow()
                session.add(job)
                await session.commit()

                logger.info(
                    "Job %s unchanged after recheck, skipped AI pipeline",
                    job.platform_job_id,
                )
                return
            
            if outcome != "enriched":
                job.status = JobStatus.FAILED
                session.add(job)
                session.commit()

                logger.warning(
                    "Unknown enrichment outcome '%s' for job_id=%s",
                    outcome,
                    job.platform_job_id,
                )
                return
            
            detail = result["detail"]
            extracted = result["extracted"]

            job.title = detail.title
            job.description = detail.description
            job.company_name = detail.company_name
            job.company_about = detail.company_about
            job.salary = detail.salary

            if detail.location:
                job.location = detail.location

            job.tools_and_technologies = extracted.get("tools_and_technologies", [])
            job.competencies = extracted.get("competencies", [])
            job.soft_skills = extracted.get("soft_skills", [])
            job.domain = extracted.get("domain")
            job.seniority_level = extracted.get("seniority_level", "unspecified")

            job.skills_vector = result.get("vector")
            job.content_hash = result.get("content_hash")
            job.scraped_at = _utcnow()
            job.status = JobStatus.ENRICHED

            session.add(job)
            await session.commit()

            logger.info(
                "Enriched job_id=%s (%s)",
                job.platform_job_id,
                job.title,
            )