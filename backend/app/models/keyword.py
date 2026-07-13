from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from app.models.association import JobKeywordLink


class SearchKeyword(SQLModel, table=True):
    __tablename__ = "search_keywords"

    id: Optional[int] = Field(default=None, primary_key=True)
    keyword: str = Field(index=True, unique=True)
    last_scraped_at: Optional[datetime] = Field(default=None) 
    jobs: List["Job"] = Relationship(back_populates="keywords", link_model=JobKeywordLink)