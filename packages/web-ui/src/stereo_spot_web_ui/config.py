"""
App config from environment with defaults.
Single place for env-derived values used across the web UI.
Uses pydantic-settings so all env vars are validated and documented in one model.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class WebUISettings(BaseSettings):
    """
    All environment variables used by the web UI.
    Env vars are read from os.environ (UPPER_SNAKE_CASE by default).
    """

    # Used for "Open logs" CloudWatch Logs Insights link on job detail (typically set in ECS).
    name_prefix: str | None = None
    logs_region: str | None = None

    model_config = SettingsConfigDict(
        env_file=None,  # We load .env via bootstrap_env() in main so env is ready
        extra="ignore",
    )


def get_settings() -> WebUISettings:
    """Return validated settings from current environment."""
    return WebUISettings()


def bootstrap_env() -> None:
    """
    Load .env from path in STEREOSPOT_ENV_FILE if set (e.g. by nx run web-ui:serve).
    Call once at app startup before using get_settings() so vars from the file are in os.environ.
    """
    import os

    import dotenv

    path = os.environ.get("STEREOSPOT_ENV_FILE")
    if path:
        dotenv.load_dotenv(Path(path).resolve())
