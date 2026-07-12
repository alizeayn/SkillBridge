from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LIST_URL: str = "https://candidateapi.jobvision.ir/api/v1/JobPost/List"
DETAIL_URL: str = "https://candidateapi.jobvision.ir/api/v1/JobPost/Detail?jobPostId="



class JobVisionScraper(BaseScraper):

    source_name: str  = "jobvision"

    async def fetch_raw_jobs(self, page_size: int = 30, max_pages: int = 1) -> List[Dict[str, Any]]:
        collected_jobs: List[Dict[str, Any]] = []

        for current_page in range(1, max_pages +1):
            payload: Dict[str, Any] = {
                "page": current_page,
                "pageSize": page_size,
                "sort": 0,
            }

            try:
                list_response = await self._safe_post(LIST_URL, json=payload)
            except Exception: # noqa: BLE001
                logger.exception(
                    "Unexpected error while posting to List API (page=%d) for '%s'",
                    current_page,
                    self.source_name,
                )
                break

            if list_response is None:
                logger.warning(
                    "No response from List API on page %d for '%s'; skipping page",
                    current_page,
                    self.source_name,
                )
                break

            try: 
                lis_json: Dict[str, Any] = list_response.json()
            except ValueError:
                logger.error(
                    "Failed to decode JSON from List API on page %d for '%s'",
                    current_page,
                    self.source_name,
                )
                break

            job_items: List[Dict[str, Any]] = (lis_json.get("data") or {}).get("jobPosts") or []
            if not job_items:
                logger.info(
                    "No job items found on page %d for '%s'; stopping pagination",
                    current_page,
                    self.source_name,
                )
                break

            for job_item in job_items:
                job_id: Optional[Any] = job_item.get("id") or job_item.get("jobPostId")

                if job_id is None:
                    logger.warning(
                        "Skipping job item with no identifiable id/jobPostId for '%s'",
                        self.source_name,
                    )
                    continue

                try:
                    detail_response = await self._safe_get(
                        f"{DETAIL_URL}?jobPostId={job_id}"
                    )
                except Exception: # noqa: BLE001
                    logger.exception(
                        "Unexpected error fetching detail for job_id=%s on '%s'",
                        job_id,
                        self.source_name,
                    )
                    await self._throttle()
                    continue

                if detail_response is None:
                    logger.warning(
                       "No detail response for job_id=%s on '%s'; skipping",
                        job_id,
                        self.source_name, 
                    )
                    await self._throttle()
                    continue

                if detail_response.status_code != 200:
                    logger.warning(
                        "Detail API returned status %d for job_id=%s on '%s'",
                        detail_response.status_code,
                        job_id,
                        self.source_name,
                    )
                    await self._throttle()
                    continue
                try:
                    detail_json: Dict[str, Any] = detail_response.json()
                except ValueError:
                    logger.error(
                        "Failed to decode JSON detail response for job_id=%s on '%s'",
                        job_id,
                        self.source_name,
                    )
                    await self._throttle()
                    continue

                detail_json.setdefault("id", job_id)
                collected_jobs.append(detail_json)

                await self._throttle()

        logger.info(
            "Collected %d raw job payloads for '%s' across %d page(s)",
            len(collected_jobs),
            self.source_name,
            max_pages,
        )
        return collected_jobs


    def parse_job_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:

        job_id: Any = raw_data.get("id") or raw_data.get("jobPostId")

        description_html: str = raw_data.get("description") or ""
        try:
            cleaned_description: str = BeautifulSoup(
                description_html, "html.parser"
            ).get_text(separator="\n").strip()
        except Exception: # noqa BLE001
            logger.exception(
                "Failed to strip HTML from description for job_id=%s on '%s'",
                job_id,
                self.source_name,
            )
            cleaned_description = description_html
        
        company: Dict[str, Any] = raw_data.get("company") or {}
        company_name: Optional[str] = raw_data.get("name_fa")
        company_about: Optional[str] = raw_data.get("company_type")

        location: Dict[str, Any] = raw_data.get("loccation") or {}
        location_city: Optional[str] = location.get("city")

        published_at: Optional[datetime] = self._parse_published_at(raw_data)

        return {
            "platform": "jobvision",
            "platform_job_id": str(job_id) if job_id is not None else None,
            "title": raw_data.get("title"),
            "description": cleaned_description or None,
            "company_name": company_name,
            "company_about": company_about,
            "salary": None,
            "location": location_city,
            "published_at": published_at,
        }
    
    def _parse_published_at(self, raw_data: Dict[str,Any]) -> Optional[datetime]:
        raw_timestamp: Optional[str] = raw_data.get("activation_time") or raw_data.get("first_activation")

        if not raw_timestamp:
            return None
        
        normalized_timestamp = raw_timestamp.replace("Z", "+00:00")

        try:
            return datetime.fromisoformat(normalized_timestamp)
        except ValueError:
            logger.warning(
                "Could not parse published_at value '%s' for '%s'",
                raw_timestamp,
                self.source_name,
            )
            return None