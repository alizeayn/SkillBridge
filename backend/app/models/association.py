from uuid import UUID
from typing import Optional
from sqlmodel import SQLModel, Field

class JobKeywordLink(SQLModel, table=True):
    __tablename__ = "job_keyword_association"
    job_id: UUID = Field(foreign_key="jobs.id", primary_key=True)
    keyword_id: int = Field(foreign_key="search_keywords.id", primary_key=True)