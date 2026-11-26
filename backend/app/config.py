"""Central application settings.

All values can be overridden through environment variables using the
``TEAMPDF_`` prefix, or through a ``.env`` file in the working directory.

Example::

    TEAMPDF_DEBUG=false
    TEAMPDF_LOG_LEVEL=WARNING
    TEAMPDF_CORS_ORIGINS=["http://localhost:3000"]
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the TeamPDF Studio API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TEAMPDF_",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "TeamPDF Studio"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True

    # --- HTTP ---
    api_prefix: str = "/api/v1"
    cors_origins: List[str] = Field(
        default=[
            "http://localhost",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    )

    # --- Logging ---
    log_level: str = "INFO"

    # --- Uploads (used from Phase 2 onwards) ---
    max_upload_size_mb: int = 100


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()
