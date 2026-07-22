from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.models.keyword import SearchKeyword
from app.models.association import JobKeywordLink
from app.scrapers.base import BaseScraper, JobSummary
from app.services.ai_analyzer import AIAnalyzer

logger = logging.getLogger(__name__)


class ScraperManager:
    def __init__(self, scrapers: List[BaseScraper], ai_analyzer: AIAnalyzer) -> None:
        self.scrapers: Dict[str, BaseScraper] = {s.source_name: s for s in scrapers}
        self.ai_analyzer = ai_analyzer

    async def run_discover(
            self,
            keywords: List[str],
            location: str,
            session: AsyncSession,
    ) -> None:
        for scraper in self.scrapers.values():
            for raw_keyword in keywords:
                keyword = raw_keyword.strip()
                keyword_row = await self._get_or_create_keyword(keyword, session)

                page = 1
                while True:
                    summaries = await scraper.discover(keyword, location, page)
                    if not summaries:
                        break

                    for summary in summaries:
                        await self._upsert_summary(
                            platform=scraper.source_name,
                            summary=summary,
                            keyword_id=keyword_row.id,
                            session=session,

                        )
                    page +=1

                    keyword_row.last_scraped_at = datetime.utcnow()
                    session.add(keyword_row)
                    await session.commit

                    logger.info(
                        "Discovery finished: keyword='%s' platform='%s'",
                        keyword, scraper.source_name,
                    )
    async def _get_or_create_keyword(self, keyword: str, session: AsyncSession) -> SearchKeyword:
        insert_stmt = pg_insert(SearchKeyword).values(keyword=keyword).on_conflict_do_nothing(
            index_elements=["keyword"]
        )
        await session.execute(insert_stmt)
        await session.commit()

        result = await session.execute(
            select(SearchKeyword).where(SearchKeyword.keyword == keyword)
        )
        return result.scalar_one()
    
    async def _upsert_summary(
            self,
            platform: str,
            summary: JobSummary,
            keyword_id: int,
            session: AsyncSession,
    ) -> None:
        result = await session.execute(
            select(Job).where(
                Job.platform == platform,
                Job.platform_job_id == summary.platform_job_id,
            )
        )
        job: Optional[Job] = result.scalar_one_or_none()
        if job is None:
            insert_stmt = pg_insert(Job).values(
                platform=platform,
                platform_job_id=summary.platform_job_id,
                title=summary.title,
                description="",
                company_name="",
                location=summary.location,
                external_activated_at=summary.external_activated_at,
                expires_at=summary.expires_at,
                is_expired=summary.is_expired,
                last_seen_at=datetime.utcnow(),
                status=JobStatus.PENDING_DETAIL,
            ).on_conflict_do_nothing(constraint="uq_job_platform_id")
            await session.execute(insert_stmt)
            await session.commit()

            result = await session.execute(
                select(Job).where(
                    Job.platform == platform,
                    Job.platform_job_id == summary.platform_job_id,
                )
            )
            job = result.scalar_one()
        else:
            job.last_seen_at = datetime.utcnow
            job.is_expired = summary.is_expired
            job.expires_at = summary.expires_at

            if (
                job.status == JobStatus.ENRICHED
                and summary.external_activated_at != job.external_activated_at
            ):
                job.status = JobStatus.NEEDS_RECHECK
            job.external_activated_at = summary.external_activated_at
            session.add(job)
            await session.commit()
        
        link_stmt = pg_insert(JobKeywordLink).values(
            job_id=job.id , keyword_id=keyword_id
        ).on_conflict_do_nothing()
        await session.execute(link_stmt)
        await session.commit()    



    async def run_enrichment(self, session: AsyncSession) -> None:
        jobs = await self._get_jobs_needing_enrichment(session)
        logger.info("Found %d job(s) needing enrichment", len(jobs))

        for job in jobs:
            scraper = self.scrapers.get(job.platform)
            if scraper is None:
                logger.error("No scraper registered for platform '%s'", job.platform)
                job.status = JobStatus.FAILED
                session.add(job)
                await session.commit()
                continue

            detail = await scraper.fetch_detail(job.platform_job_id)
            if detail is None:
                job.status = JobStatus.FAILED
                session.add(job)
                session.commit()
                continue

            new_hash = self._compute_content_hash(detail.title, detail.description, detail.salary)

            if job.status == JobStatus.NEEDS_RECHECK and new_hash == job.content_hash:
                job.status =  JobStatus.ENRICHED
                job.scraped_at = datetime.utcnow()
                session.add(job)
                await session.commit()
                logger.info(
                    "Job %s unchanged after recheck, skipped AI pipeline", job.platform_job_id
                )
                continue

            try:
                extracted = await self.ai_analyzer.extract_structured(detail.description)
                vector = await self.ai_analyzer.embed_skills(
                    extracted.get("tools_and_technologies", [])
                )
            except Exception: # noqa: BELE001
                logger. exception("AI pipeline failed for job_id=%s", job.platform_job_id)
                job.status = JobStatus.FAILED
                session.add(job)
                await session.commit()
                continue

            job.title = detail.title
            job.description = detail.description
            job.company_name = detail.company_name
            job.company_about = detail.company_about
            job.salary = detail.salary
            job.location = detail.location

            job.tools_and_technologies = extracted.get("tools_and_technologies", [])
            job.competencies = extracted.get("competencies", [])
            job.soft_skills = extracted.get = extracted.get("soft_skills", [])
            job.domain = extracted.get("domain")
            job.seniority_level = extracted.get("seniority_level", "unspecified")
            job.skills_vector = vector

            job.content_hash = new_hash
            job.scraped_at = datetime.utcnow()
            job.status = JobStatus.ENRICHED

            session.add(job)
            await session.commit()
            logger.info("Enriched job_id=%s (%s)", job.platform_job_id, job.title)

    async def _get_jobs_needing_enrichment(self, session: AsyncSession) -> List[Job]:
        result = await session.execute(
            select(Job).where(
                Job.status.in_([JobStatus.PENDING_DETAIL, JobStatus.NEEDS_RECHECK])
            )
        )
        return list(result.scalars().all())
    
    @staticmethod
    def _compute_content_hash(title: str, description: str, salary: Optional[str]) -> str:
        raw = f"{title}|{description}|{salary or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()     
