from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import SQLModel, Field, Relationship
from pgvector.sqlalchemy import Vector


class SkillCategory:
    TOOL = "tool"
    COMPETENCY = "competency"
    SOFT_SKILL = "soft_skill"


class Skill(SQLModel, table=True):

    __tablename__ = "skills"

    id: Optional[int] = Field(default=None, primary_key=True)
    canonical_name: str = Field(index=True)
    normalized_key: str = Field(index=True)
    category: str = Field(index=True)
    embedding: Optional[List[float]] = Field(
        default=None,
        sa_column=Column(Vector(4096), nullable=True),
    )
    frequency: int = Field(default=0)
    source: str = Field(default="auto")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    aliases: List["SkillAlias"] = Relationship(back_populates="skill")

    __table_args__ = (
        UniqueConstraint("normalized_key", "category", name="uq_skill_key_category"),
    )


class SkillAlias(SQLModel, table=True):

    __tablename__ = "skill_aliases"

    id: Optional[int] = Field(default=None, primary_key=True)

    skill_id: int = Field(foreign_key="skills.id", index=True)
    alias: str
    normalized_alias: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    skill: Optional[Skill] = Relationship(back_populates="aliases")
    __table_args__ = (
        UniqueConstraint("normalized_alias", name="uq_alias_normalized"),
    )