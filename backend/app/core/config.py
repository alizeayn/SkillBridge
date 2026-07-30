from typing import List
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict



class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_ENV: str = "dev"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Database
    POSTGRES_USER: str = "skillbridge_user"
    POSTGRES_PASSWORD: str = "skillbridge_password"
    POSTGRES_DB: str = "skillbridge_dev"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_ECHO: bool = False

    # AI / OpenRouter
    OPENROUTER_API_KEY: str
    AI_EMBEDDING_MODEL: str
    AI_CHAT_MODEL: str
    AI_CHAT_MODEL_LIGHT: str
    AI_BASE_URL: str = "https://openrouter.ai/api/v1"
    AI_TIMEOUT: float = 60.0
    AI_MAX_RETRIES: int = 2

    # Scraper
    SCRAPER_REQUEST_DELAY: float = 0.5
    SCRAPER_CONNECT_TIMEOUT: float = 10.0
    SCRAPER_READ_TIMEOUT: float = 20.0
    SCRAPER_WRITE_TIMEOUT: float = 10.0
    SCRAPER_POOL_TIMEOUT: float = 5.0

    SCRAPER_MAX_RETRIES: int = 3
    SCRAPER_RETRY_BACKOFF_FACTOR: float = 1.5

    SCRAPER_PAGE_SIZE: int = 30
    SCRAPER_MAX_PAGES: int = 100

    # Pipeline
    ENRICHMENT_CONCURRENCY: int = 10
    DEFAULT_LOCATION: str = "Tehran"
    DISCOVERY_KEYWORDS: List[str] = Field(
        default_factory=lambda: [
            "هوش مصنوعی / AI",
            "بک‌اند / Backend",
            "FastAPI",
            "Python",
            "Data Engineer",
        ]
    )

    # Scheduler
    SCHEDULER_ENABLED: bool = False
    DISCOVERY_INTERVAL_MINUTES: int = 360
    ENRICHMENT_INTERVAL_MINUTES: int = 60

    # API
    CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: ["*"]
    )

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg://"
            f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}"
            f"/{self.POSTGRES_DB}"
        )
    
settings = Settings()