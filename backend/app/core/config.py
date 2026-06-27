from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict



class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    POSTGRES_USER: str = "skillbridge_user"
    POSTGRES_PASSWORD: str = "skillbridge_password"
    POSTGRES_DB: str = "skillbridge_dev"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # AI / OpenRouter — no defaults, must be provided via environment or .env
    OPENROUTER_API_KEY: str
    AI_EMBEDDING_MODEL: str
    AI_CHAT_MODEL: str


    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        """Construct PostgreSQL connection URL using the psycopg driver."""
        return (
            f"postgresql+psycopg://"
            f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}"
            f"/{self.POSTGRES_DB}"
        )
    
settings = Settings()