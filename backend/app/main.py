import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.scrapers.jobvision import JobVisionScraper
from app.services.ai_analyzer import AIAnalyzer
from app.services.scraper_manager import ScraperManager


logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def perdic_discovery(manager: ScraperManager) -> None:
    interval_seconds = settings.DISCOVERY_INTERVAL_MINUTES * 60

    while True:
        try:
            logger.info("Scheduled discovery started")

            async with AsyncSessionLocal() as session:
                await manager.run_discovery(
                    keywords=settings.DISCOVERY_KEYWORDS,
                    location=settings.DEFAULT_LOCATION,
                    session=session,
                )
            logger.info("Scheduled discovery finished")
        except Exception:
            logger.exception("Scheduled discovery failed")
        await asyncio.sleep(interval_seconds)


async def periodic_enrichment(manager: ScraperManager) -> None:
    interval_seconds = settings.ENRICHMENT_INTERVAL_MINUTES * 60

    while True:
        try:
            logger.info("Scheduled enrichment started")

            async with AsyncSessionLocal() as session:
                await manager.run_enrichment(
                    session=session,
                    concurrency=settings.ENRICHMENT_CONCURRENCY,
                )
            logger.info("Scheduled enrichment finished")
        except Exception:
            logger.exception("Scheduled enrichment failed")
            await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV != "prod":
        logger.info("Initializing database schema (dev mode)")
        await init_db()
    else:
        logger.info("Skipping create_all in prod; Alembic migrations expected")
    scraper = JobVisionScraper(
        request_delay=settings.SCRAPER_REQUEST_DELAY,
    )

    ai_analyzer = AIAnalyzer()

    manager = ScraperManager(
        scrapers=[scraper],
        ai_analyzer=ai_analyzer,
    )
    
    app.state.scraper = scraper
    app.state.ai_analyzer = ai_analyzer
    app.state.scraper_manager = manager

    background_tasks = list[asyncio.Task] = []

    if settings.SCHEDULER_ENABLED:
        logger.info(
            "Scheduler enabled: discovery every %d min, enrichment every %d min",
            settings.DISCOVERY_INTERVAL_MINUTES,
            settings.ENRICHMENT_INTERVAL_MINUTES,
        )
        
        background_tasks.append(
            asyncio.create_task(perdic_discovery(manager))
        )
        background_tasks.append(
            asyncio.create_task(periodic_enrichment(manager))
        )
    else:
        logger.info("Scheduler disabled")
    logger.info("SkillBridge API started (env=%s)", settings.APP_ENV)
    
    yield

    logger.info("Shutting down SkillBridge API")

    for task in background_tasks:
        task.cancel()
    
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
    
    await scraper.close()

app = FastAPI(
    title="SkillBridge API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:

    db_status = "ok"
    db_error = None

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "error"
        db_error = exc.__class__.__name__
        logger.exception("Health check DB failed")

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "app_env": settings.APP_ENV,
        "database": db_status,
        "database_error": db_error,
        "scheduler_enabled": settings.SCHEDULER_ENABLED,
    }