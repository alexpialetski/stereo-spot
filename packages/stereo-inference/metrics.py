"""Metrics adapter facade. Routes by METRICS_PROVIDER (aws|gcp|none). Default aws."""

from __future__ import annotations

import os


def emit_conversion_metrics(duration_seconds: float, size_bytes: int) -> None:
    provider = (os.environ.get("METRICS_PROVIDER") or "aws").strip().lower()
    if provider == "none" or provider == "":
        return
    if provider == "aws":
        import metrics_aws
        metrics_aws.emit_conversion_metrics(duration_seconds, size_bytes)
    elif provider == "gcp":
        import metrics_gcp
        metrics_gcp.emit_conversion_metrics(duration_seconds, size_bytes)
    # else: no-op for unknown provider
