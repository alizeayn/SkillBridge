from typing import AsyncGenerator
from sqlmodel import SQLModel, create_engine, Session

from app.core.config import settings


engine = create_engine(settings.DATABASE_URL, echo=True)


def create_db_and_tables() -> None:
    """Create all database tables by importing models to register them with SQLModel metadata."""    
    
    import app.models.association  # noqa: F401
    import app.models.job  # noqa: F401
    import app.models.keyword  # noqa: F401

    SQLModel.metadata.create_all(engine)

async def get_session() -> AsyncGenerator[Session, None]:
    """Get a new database session."""
    with Session(engine) as session:
        yield session
    
