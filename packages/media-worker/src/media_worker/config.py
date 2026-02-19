"""
App config from environment with defaults.
Uses pydantic-settings so all env vars are validated and documented in one model.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class MediaWorkerSettings(BaseSettings):
    """
    All environment variables used by the media worker.
    Env vars are read from os.environ (UPPER_SNAKE_CASE by default).
    """

    model_config = SettingsConfigDict(extra="ignore")

    # Chunking: segment length in seconds for ffmpeg split
    chunk_segment_duration_sec: int = 300


def get_settings() -> MediaWorkerSettings:
    """Return validated settings from current environment."""
    return MediaWorkerSettings()
