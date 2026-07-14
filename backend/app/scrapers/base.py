from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_TIMEOUT: httpx.Timeout = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0)


@dataclass
class JobSummary:
    platform_job_id: str
    title: str
    location: str
    external_activated_at: Optional[datetime]
    expires_at: Optional[datetime]
    is_expired: bool


@dataclass
class JobDetail:
    platform_job_id: str
    title: str
    description: str
    company_name: str
    company_about: Optional[str]
    salary: Optional[str]
    location: str


class BaseScraper(abc.ABC):
    source_name: str = "base"

    def __init__(
            self,
            client: Optional[httpx.AsyncClient] = None,
            *,
            headers: Optional[Dict[str, str]] = None,
            timeout: httpx.Timeout = DEFAULT_TIMEOUT,
            request_delay: float = 0.5,
    ) -> None:
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.request_delay: float = request_delay

        if client is not None:
            self.client: httpx.AsyncClient = client
            self._owns_client: bool = False
        else:
            self.client= httpx.AsyncClient(headers=merged_headers, timeout=timeout)
            self._owns_client = True

        logger.info(
            "Initialized scraper '%s' (owns_client=%s, request_delay=%.2f)",
            self.source_name,
            self._owns_client,
            self.request_delay,
        )
    
    async def __aenter__(self) -> "BaseScraper":
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and not self.client.is_closed:
            await self.client.aclose()
            logger.info("Closed HTTP client for scraper '%s'", self.source_name)
    
    async def _throttle(self) -> None:
        if self.request_delay > 0:
            await asyncio.sleep(self.request_delay)
    
    async def _safe_get(
            self,
            url: str,
            *,
            params: Optional[Dict[str, Any]] = None,
            **kwargs: Any
    ) -> Optional[httpx.Response]:
        try:
            return await self.client.get(url, params=params, **kwargs)
        except httpx.TimeoutException:
            logger.warning("Timeout while fetching '%s' for scraper '%s'", url, self.source_name)
            return None
        except httpx.HTTPError as exc:
            logger.error("Network error while fetching '%s' for scraper '%s': %s", url, self.source_name, exc)
            return None
    
    async def _safe_post(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Optional[httpx.Response]:
        try:
            return await self.client.post(url, params=params, **kwargs)
        except httpx.TimeoutException:
            logger.warning("Timeout while posting to '%s' for scraper '%s'", url, self.source_name)
            return None
        except httpx.HTTPError as exc:
            logger.error("Network error while posting to '%s' for scraper '%s': %s", url, self.source_name, exc)
            return None
    


    @abc.abstractmethod
    async def discover(
        self,
        keyword: str,
        location: str,
        page:int,
        page_size: int = 30,
    ) -> List[JobSummary]:
        raise NotImplementedError
    
    @abc.abstractmethod
    async def fetch_detail(self, platform_job_id: str) -> Optional[JobDetail]:
        raise NotImplementedError
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source='{self.source_name}'>"