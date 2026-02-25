"""Tests for conversion_metrics_emitter_from_env: provider selection (aws vs no-op)."""

from __future__ import annotations

from unittest.mock import patch

from stereo_spot_shared import NoOpConversionMetricsEmitter

from stereo_spot_adapters.env_config import conversion_metrics_emitter_from_env


def test_emit_none_provider_returns_no_op() -> None:
    with patch.dict("os.environ", {"METRICS_PROVIDER": "none"}, clear=False):
        emitter = conversion_metrics_emitter_from_env()
    assert isinstance(emitter, NoOpConversionMetricsEmitter)
    emitter.emit_conversion_metrics(10.0, 1_000_000)  # no raise


def test_emit_gcp_provider_returns_no_op() -> None:
    with patch.dict("os.environ", {"METRICS_PROVIDER": "gcp"}, clear=False):
        emitter = conversion_metrics_emitter_from_env()
    assert isinstance(emitter, NoOpConversionMetricsEmitter)


def test_emit_aws_returns_cloudwatch_emitter() -> None:
    from stereo_spot_aws_adapters.conversion_metrics import CloudWatchConversionMetricsEmitter
    with patch.dict("os.environ", {"METRICS_PROVIDER": "aws", "PLATFORM": "aws"}, clear=False):
        emitter = conversion_metrics_emitter_from_env()
    assert isinstance(emitter, CloudWatchConversionMetricsEmitter)


def test_emit_default_aws_when_unset() -> None:
    from stereo_spot_aws_adapters.conversion_metrics import CloudWatchConversionMetricsEmitter
    with patch.dict("os.environ", {"PLATFORM": "aws"}, clear=False):
        if "METRICS_PROVIDER" in __import__("os").environ:
            del __import__("os").environ["METRICS_PROVIDER"]
        emitter = conversion_metrics_emitter_from_env()
    assert isinstance(emitter, CloudWatchConversionMetricsEmitter)
