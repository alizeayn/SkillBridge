from datetime import datetime
from enum import Enum
from typing import Optional, List
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON, UniqueConstraint
from pgvector.sqlalchemy import Vector

from app.models.association import JobKeywordLink


class JobStatus(str, Enum):
    PENDING_DETAIL = "pending_detail"
    NEEDS_RECHECK = "needs_recheck"
    ENRICHED = "enriched"
    FAILED = "failed"




class Job(SQLModel, table=True):
    __tablename__= "jobs"
    __table_args__ = (
        UniqueConstraint(
            "platform", "platform_id", name="uq_job_platform_id"
        )
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    platform: str = Field(index=True)
    platform_job_id: str = Field(index=True)
    title: str
    description: str
    company_name: str
    company_about: Optional[str] = Field(default=None)
    salary : Optional[str] = Field(default=None)
    location: str = Field(default="Tehran")
    status: JobStatus = Field(default=JobStatus.PENDING_DETAIL, index=True)
    published_at: Optional[datetime] = Field(default=None)
    external_activated_at: Optional[datetime] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None)
    is_expired: bool = Field(default=False, index=True)
    scraped_at: Optional[datetime] = Field(default=None)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    content_hash: Optional[str] = Field(default=None, index=True)
    tools_and_technologies: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    competencies: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    soft_skills: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    domain: Optional[str] = Field(default=None)
    seniority_level: Optional[str] = Field(default="unspecified") 
    skills_vector: Optional[list] =Field(
        default=None,
        sa_column=Column(Vector(2560))
    )                                                   
    keywords: List["SearchKeyword"] = Relationship(
        back_populates="jobs",
        link_model=JobKeywordLink
    )