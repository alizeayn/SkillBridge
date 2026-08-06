from __future__ import annotations
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from httpx import Response
from app.core.config import settings
from app.scrapers.base import BaseScraper, JobSummary, JobDetail

logger = logging.getLogger(__name__)

LIST_URL: str = "https://candidateapi.jobvision.ir/api/v1/JobPost/List"
DETAIL_URL: str = "https://candidateapi.jobvision.ir/api/v1/JobPost/Detail"

DEFAULT_SORT_BY: int = 1

class JobVisionScraper(BaseScraper):
    source_name: str = "jobvision"

    async def discover(
            self,
            keyword: str,
            location: str,
            page: int,
            page_size: Optional[int] = None,
    ) -> List[JobSummary]:
        effective_page_size = (
            page_size
            if page_size is not None
            else settings.SCRAPER_PAGE_SIZE
        )

        payload: Dict[str, Any] = {
            "pageSize": effective_page_size,
            "requestedPage": page,
            "locationWrapper": location,
            "keyword": keyword,
            "sortBy":DEFAULT_SORT_BY,
            "searchID": None,
        }

        response = await self._safe_post(LIST_URL, json=payload)
        if response is None:
            logger.warning(
                "No response from List API (keyword='%s', page=%d) for '%s'",
                keyword, page, self.source_name,
            )
            return[]
        
        if response.status_code != 200:
            logger.warning(
                "List API returned status %d (keyword='%s', page=%d) for '%s'",
                response.status_code, keyword, page, self.source_name,
            )
            return []
        
        payload_json = self._safe_json(
            response,
            context="List API",
            details=f"keyword='{keyword}', page={page}",
        )
        if payload_json is None:
            return []
        
        if not payload_json.get("isSuccess"):
            logger.warning(
                "List API isSuccess=False (keyword='%s', page=%d) for '%s'",
                keyword, page, self.source_name,
            )
            return []
        
        job_items: List[Dict[str, Any]] = (payload_json.get("data") or {}).get("jobPosts") or []

        summaries: List[JobSummary] = []
        for item in job_items:
            summary = self._parse_summary(item)
            if summary is not None:
                summaries.append(summary)
        
        logger.info(
            "Discovered %d job summaries (keyword='%s', page=%d) for '%s'",
            len(summaries), keyword, page, self.source_name,
        )
        return summaries
    
    def _parse_summary(self, item: Dict[str, Any]) -> Optional[JobSummary]:
        job_id: Any = item.get("id")
        if job_id is None:
            logger.warning("Skipping job summary with no 'id' for '%s'", self.source_name)
            return None
        
        location_block: Dict[str, Any] = item.get("location") or {}
        city_title: str = ((location_block.get("city") or {}).get("titleFa")) or ""

        activation: Dict[str, Any] = item.get("activationTime") or {}
        expire: Dict[str, Any] = item.get("expireTime") or {}

        return JobSummary(
            platform_job_id=str(job_id),
            title=item.get("title") or "",
            location=city_title,
            external_activated_at=self._parse_iso(activation.get("date")),
            expires_at=self._parse_iso(expire.get("date")),
            is_expired=bool(expire.get("isExpired", False)),

        )
    


    async def fetch_detail(self, platform_job_id: str) -> Optional[JobDetail]:
        response = await self._safe_get(
            DETAIL_URL, params={"jobPostId": platform_job_id}
        )
        if response is None:
            logger.warning(
                "No response from Detail API (job_id=%s) for '%s'",
                platform_job_id, self.source_name,
            )
            return None
        
        if response.status_code != 200:
            logger.warning(
                "Detail API returned status %d (job_id=%s) for '%s'",
                response.status_code, platform_job_id, self.source_name,
            )
            return None
        
        payload_json = self._safe_json(
            response,
            context="Detail API",
            details=f"job_id={platform_job_id}",
        )
        if payload_json is None:
            return None
        
        if not payload_json.get("isSuccess"):
            logger.warning(
                "Detail API isSuccess=False (job_id=%s) for '%s'",
                platform_job_id, self.source_name,
            )
            return None
        
        data: Dict[str, Any] = payload_json.get("data") or {}
        
        return self._parse_detail(data)
    
    def _parse_detail(self, data:Dict[str, Any]) -> Optional[JobDetail]:
        job_id: Any = data.get("id")
        if job_id is None:
            logger.warning("Skipping job detail with no 'id' for '%s'", self.source_name)
            return None
        
        cleaned_description = self._clean_html(data.get("description") or "")

        company: Dict[str, Any] = data.get("company") or {}
        company_name: str = ((company.get("name") or {}).get("titleFa")) or ""
        company_about: Optional[str] = (
            (company.get("shortDescription") or {}).get("titleFa")
            or (company.get("description") or {}).get("titleFa")
            or None
        )

        location_block: Dict[str, Any] = data.get("location") or {}
        city_title: str = ((location_block.get("city") or {}).get("titleFa")) or ""

        salary_block: Optional[Dict[str, Any]] = data.get("salary")
        salary_text: Optional[str] = (
            salary_block.get("titleFa")
            if isinstance(salary_block, dict)
            else None
        )

        return JobDetail(
            platform_job_id=str(job_id),
            title=data.get("title") or "",
            description=cleaned_description,
            company_name=company_name,
            company_about=company_about,
            salary=salary_text,
            location=city_title,
        )
    
    def _safe_json(
            self,
            response: Response,
            *,
            context: str,
            details:str,
    ) -> Optional[Dict[str, Any]]:
        try:
            payload = response.json()
        except ValueError:
            logger.error(
                "Failed to decode JSON from %s (%s, platform='%s')",
                context,
                details,
                self.source_name,
            )
            return None
        
        if not isinstance(payload, dict):
            logger.error(
                "%s returned non-object JSON (%s, platform='%s')",
                context,
                details,
                self.source_name,
            )
            return None
        return payload

    


    @staticmethod
    def _clean_html(raw_html: str) -> str:
        if not raw_html:
            return ""
        try:
            return BeautifulSoup(raw_html, "html.parser").get_text(separator="\n").strip()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to strip HTML from description")
            return raw_html

    @staticmethod
    def _parse_iso(raw_timestamp: Optional[str]) -> Optional[datetime]:
        if not raw_timestamp:
            return None
        try:
            return datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Could not parse ISO timestamp '%s'", raw_timestamp)
            return None