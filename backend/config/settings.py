from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # App Configuration
    APP_NAME: str = "AniOS"
    DEBUG: bool = False
    PORT: int = 8000
    
    # Database - PostgreSQL with pgvector
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "anios_db"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    
    # Redis Configuration
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    # AI / LLM (LM Studio / OpenAI Compatible)
    LLM_BASE_URL: str = "http://localhost:1234/v1"
    LLM_MODEL: str = "local-model"
    LLM_API_KEY: str = Field("lm-studio", alias="LLM_API_KEY")

    # JWT Authentication
    SECRET_KEY: str = Field(..., alias="SECRET_KEY")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()