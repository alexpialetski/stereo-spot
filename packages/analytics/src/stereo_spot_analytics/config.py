"""
Normalized config for the analytics gather command.

Env vars and defaults in one place; CLI args override after loading .env.
Uses pydantic-settings so all env-derived values are validated and documented.
"""

from __future__ import annotations

import os
from pathlib import Path

import dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def load_dotenv(path: Path) -> None:
    """
    Load .env from path into os.environ (same approach as web-ui bootstrap_env).

    Uses python-dotenv for consistent parsing with the rest of the repo.
    """
    if path.exists():
        dotenv.load_dotenv(path.resolve())


class AnalyticsGatherSettings(BaseSettings):
    """
    All env-derived and default values for the gather command.

    Load .env first (via load_dotenv(env_file)), then instantiate from current
    os.environ. CLI can override output and period_hours after construction.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        env_prefix="",  # no prefix
    )

    # Env file path (set by Nx configuration or --env-file; not read from .env)
    env_file: Path | None = Field(
        None,
        description="Path to .env to load (ANALYTICS_ENV_FILE or --env-file)",
    )
    output: Path = Field(
        default=Path("docs/analytics/latest.json"),
        description="Output JSON path (ANALYTICS_OUTPUT)",
    )
    period_hours: float = Field(
        default=24.0,
        ge=0.1,
        le=720.0,
        description="Metric period in hours (ANALYTICS_PERIOD_HOURS)",
    )
    metrics_adapter: str = Field(
        default="aws",
        description="Adapter to use: aws | gcp (METRICS_ADAPTER)",
    )
    region: str = Field(
        default="us-east-1",
        description="Region (AWS_REGION or REGION)",
    )
    endpoint_name: str | None = Field(
        default=None,
        description="Inference endpoint name (SAGEMAKER_ENDPOINT_NAME)",
    )
    cloud_name: str = Field(
        default="aws",
        description="Cloud identifier for metrics dimension (ETA_CLOUD_NAME)",
    )

    @field_validator("metrics_adapter", mode="before")
    @classmethod
    def normalize_adapter(cls, v: object) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return "aws"

    @field_validator("region", mode="before")
    @classmethod
    def region_from_env(cls, v: object) -> str:
        s = (v if isinstance(v, str) else None) or ""
        s = s.strip()
        if s:
            return s
        return (
            os.environ.get("AWS_REGION")
            or os.environ.get("REGION")
            or os.environ.get("region")
            or "us-east-1"
        )

    @field_validator("endpoint_name", mode="before")
    @classmethod
    def endpoint_from_env(cls, v: object) -> str | None:
        s = (v if isinstance(v, str) else None) or ""
        s = s.strip()
        if s:
            return s
        return (
            os.environ.get("SAGEMAKER_ENDPOINT_NAME")
            or os.environ.get("sagemaker_endpoint_name")
            or None
        )

    @field_validator("cloud_name", mode="before")
    @classmethod
    def cloud_from_env(cls, v: object) -> str:
        s = (v if isinstance(v, str) else None) or ""
        s = s.strip()
        if s:
            return s or "aws"
        return (
            os.environ.get("ETA_CLOUD_NAME")
            or os.environ.get("eta_cloud_name")
            or "aws"
        )


def get_gather_settings(
    env_file: Path | None = None,
    output: Path | None = None,
    period_hours: float | None = None,
) -> AnalyticsGatherSettings:
    """
    Load .env from env_file (if set), build settings from env, apply overrides.

    Call after parsing CLI: pass args.env_file, args.output, args.period_hours.
    """
    if env_file is not None:
        load_dotenv(Path(env_file).resolve())

    settings = AnalyticsGatherSettings()

    overrides: dict[str, object] = {}
    if output is not None:
        overrides["output"] = Path(output).resolve()
    if period_hours is not None:
        overrides["period_hours"] = period_hours

    if overrides:
        settings = settings.model_copy(update=overrides)
    # Resolve relative output path to cwd
    if not settings.output.is_absolute():
        settings = settings.model_copy(
            update={"output": Path.cwd() / settings.output}
        )
    return settings
