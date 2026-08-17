from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from app.core.config import settings


logger = logging.getLogger(__name__)


AI_REQUEST_TIMEOUT: float = 60.0
AI_MAX_RETRIES: int = 3
AI_RETRY_BACKOFF_FACTOR: float = 1.5
EXTRACTION_MAX_TOKENS: int = 2048

VALID_SENIORITY_LEVELS = frozenset(
    {"intern", "junior", "mid", "senior", "lead", "unspecified"}
)


EXTRACTION_SYSTEM_PROMPT = """You are a precise information-extraction engine for job advertisements in the Iranian tech/IT job market. You extract structured data from raw job descriptions, which may be written in Persian, English, or a mix of both.

Output contract
Return ONLY a single valid JSON object matching the schema below. No markdown fences, no preamble, no explanation.

Fields
tools_and_technologies: array of explicitly named technologies (languages, frameworks, databases, cloud platforms, specific products/APIs). Use canonical forms (e.g. "React" not "React.js", "PostgreSQL" not "Postgres").

competencies: array of technical CAPABILITIES described in the text, even when no product name is attached, as short noun phrases (2-6 words). Do NOT skip a capability just because it's inside a long descriptive sentence instead of a keyword list.

soft_skills: interpersonal/behavioral skills. Merge near-duplicates.

domain: industry/business domain as a short phrase (e.g. "banking / fintech", "healthcare", "general IT services"). Return null if unclear.

seniority_level: exactly one of ["intern", "junior", "mid", "senior", "lead", "unspecified"]. Use "unspecified" if ambiguous.

Normalization
Deduplicate near-identical spellings/casings of the same tool (e.g. "Elasticsearch" / "Elastic Search" -> keep one canonical form). Do not invent information; return empty arrays when nothing is found.

Schema
{
  "tools_and_technologies": [],
  "competencies": [],
  "soft_skills": [],
  "domain": null,
  "seniority_level": "unspecified"
}
"""


class AIAnalyzer:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            base_url=settings.AI_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            timeout=AI_REQUEST_TIMEOUT,
            max_retries=0,
        )
        self.chat_model_light = settings.AI_CHAT_MODEL_LIGHT
        self.embedding_model = settings.AI_EMBEDDING_MODEL

        logger.info(
            "AIAnalyzer initialized (extraction=%s, embedding=%s)",
            self.chat_model_light,
            self.embedding_model,
        )
    

    async def extract_structured(self, description: str) -> Dict[str, Any]:
        if not description or not description.strip():
            return self._empty_extraction()
        
        try:
            raw_content = await self._call_extraction_llm(description)
        except Exception:
            logger.exception("Extraction LLM call failed after retries")
            return self._empty_extraction()
        
        parsed = self._safe_parse_json(raw_content)
        if parsed is None:
            logger.error(
                "Failed to parse extraction JSON. Raw content: %r",
                raw_content[:500],
            )
            return self._empty_extraction()
        
        return self._normalize_extraction(parsed)
    
    @retry(
        stop=stop_after_attempt(AI_MAX_RETRIES),
        wait=wait_exponential(
            multiplier=AI_RETRY_BACKOFF_FACTOR,
            min=1,
            max=30,
        ),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    async def _call_extraction_llm(self, description: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.chat_model_light,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": description},
            ],
            temperature=0,
            max_tokens=EXTRACTION_MAX_TOKENS,
        )
        return response.choices[0].message.content or ""
    

    async def embed_skills(self, skills: List[str]) -> Optional[List[float]]:
        if not skills:
            return None

        seen: set[str] = set()
        unique_skills: List[str] = []
        for skill in skills:
            if not isinstance(skill, str):
                continue
            normalized = skill.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_skills.append(skill.strip())

        if not unique_skills:
            return None

        text = ", ".join(unique_skills)

        try:
            return await self._call_embedding_llm(text)
        except Exception:
            logger.exception("Embedding LLM call failed after retries")
            return None

    @retry(
        stop=stop_after_attempt(AI_MAX_RETRIES),
        wait=wait_exponential(
            multiplier=AI_RETRY_BACKOFF_FACTOR,
            min=1,
            max=30,
        ),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_embedding_llm(self, text: str) -> List[float]:
        response = await self.client.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return response.data[0].embedding
