"""
CLI for gathering conversion metrics.

Usage:
  python -m stereo_spot_analytics gather --env-file packages/aws-infra/.env [--output path]
  stereo-spot-analytics gather --env-file packages/aws-infra/.env

Nx runs this with configuration=aws or gcp; each configuration passes the appropriate --env-file.
Config and env var normalization live in config.py (AnalyticsGatherSettings).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stereo_spot_analytics.config import get_gather_settings


def _gather_aws(
    start_time: datetime,
    end_time: datetime,
    period_seconds: int,
    region: str,
    endpoint_name: str | None,
    cloud_name: str,
):
    from stereo_spot_aws_adapters import get_conversion_metrics

    return get_conversion_metrics(
        start_time,
        end_time,
        period_seconds,
        region=region,
        endpoint_name=endpoint_name,
        cloud_name=cloud_name,
    )


def _gather_gcp(
    start_time: datetime,
    end_time: datetime,
    period_seconds: int,
    region: str,
    endpoint_name: str | None,
    cloud_name: str,
):
    raise NotImplementedError("GCP adapter not implemented yet; use METRICS_ADAPTER=aws")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gather conversion metrics for StereoSpot (AWS or GCP)"
    )
    parser.add_argument(
        "subcommand",
        nargs="?",
        default="gather",
        help="Subcommand (default: gather)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to .env (required for gather; or set ANALYTICS_ENV_FILE)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: docs/analytics/latest.json under cwd)",
    )
    parser.add_argument(
        "--period-hours",
        type=float,
        default=None,
        help="Metric period in hours (default: 24)",
    )
    args = parser.parse_args()

    if args.subcommand != "gather":
        print(f"Unknown subcommand: {args.subcommand}", file=sys.stderr)
        return 1

    env_file = args.env_file
    if env_file is None:
        env_file_str = os.environ.get("ANALYTICS_ENV_FILE")
        env_file = Path(env_file_str) if env_file_str else None

    if env_file is None:
        print(
            "Missing --env-file or ANALYTICS_ENV_FILE (set by Nx configuration)",
            file=sys.stderr,
        )
        return 1

    settings = get_gather_settings(
        env_file=env_file,
        output=args.output,
        period_hours=args.period_hours,
    )

    if not settings.endpoint_name and settings.metrics_adapter == "aws":
        print(
            "SAGEMAKER_ENDPOINT_NAME not set; SageMaker metrics will be omitted.",
            file=sys.stderr,
        )

    settings.output.parent.mkdir(parents=True, exist_ok=True)

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=settings.period_hours)
    period_seconds = 3600

    if settings.metrics_adapter == "aws":
        snapshot = _gather_aws(
            start_time,
            end_time,
            period_seconds,
            region=settings.region,
            endpoint_name=settings.endpoint_name,
            cloud_name=settings.cloud_name,
        )
    elif settings.metrics_adapter == "gcp":
        snapshot = _gather_gcp(
            start_time,
            end_time,
            period_seconds,
            region=settings.region,
            endpoint_name=settings.endpoint_name,
            cloud_name=settings.cloud_name,
        )
    else:
        print(
            f"Unknown METRICS_ADAPTER: {settings.metrics_adapter}",
            file=sys.stderr,
        )
        return 1

    payload = snapshot.model_dump()
    with open(settings.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote {settings.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
