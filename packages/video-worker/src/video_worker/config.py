"""
App config from environment with defaults.
Uses pydantic-settings so all env vars are validated and documented in one model.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class VideoWorkerSettings(BaseSettings):
    """
    All environment variables used by the video worker.
    Env vars are read from os.environ (UPPER_SNAKE_CASE by default).
    """

    model_config = SettingsConfigDict(extra="ignore")

    # Inference backend: stub | sagemaker | http
    inference_backend: str = "stub"

    # SageMaker (when inference_backend=sagemaker)
    sagemaker_endpoint_name: str = ""
    sagemaker_region: str = ""
    sagemaker_invoke_timeout_seconds: int = 1200
    sagemaker_async_poll_interval_seconds: int = 15

    # HTTP (when inference_backend=http)
    inference_http_url: str = ""

    # Max concurrent SageMaker async invocations (1–20)
    inference_max_in_flight: int = 5

    @field_validator("inference_max_in_flight", mode="before")
    @classmethod
    def parse_and_clamp_max_in_flight(cls, v: object) -> int:
        if isinstance(v, int):
            return max(1, min(v, 20))
        if isinstance(v, str):
            try:
                n = int(v)
                return max(1, min(n, 20))
            except ValueError:
                return 5
        return 5

    @property
    def use_sagemaker_backend(self) -> bool:
        return self.inference_backend.lower() == "sagemaker"

    @property
    def use_http_backend(self) -> bool:
        return self.inference_backend.lower() == "http"


def get_settings() -> VideoWorkerSettings:
    """Return validated settings from current environment."""
    return VideoWorkerSettings()
