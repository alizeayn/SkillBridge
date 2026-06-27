from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column
from pgvector.sqlalchemy import Vector

from app.models.association import JobKeywordLink



class Job(SQLModel, table=True):
    __tablename__= "jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    platform: str = Field(index=True)
    platform_job_id: str = Field(index=True)
    title: str
    description: str
    company_name: str
    company_about: Optional[str] = Field(default=None)
    salary : Optional[str] = Field(default=None)
    location: str = Field(default="Tehran")
    published_at: Optional[datetime] = Field(default=None)
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    description_vector: Optional[list] = Field(
        default=None,
        sa_column=Column(Vector(2560))
    )
    keywords: List["SearchKeyword"] = Relationship(
        back_populates="jobs",
        link_model=JobKeywordLink
    )