"""Tests for metrics facade: provider selection."""

from __future__ import annotations

from unittest.mock import patch

import metrics


def test_emit_none_provider_no_op() -> None:
    with patch.dict("os.environ", {"METRICS_PROVIDER": "none"}):
        metrics.emit_conversion_metrics(10.0, 1_000_000)
    # No exception, no call to aws/gcp


def test_emit_aws_calls_metrics_aws() -> None:
    with patch.dict("os.environ", {"METRICS_PROVIDER": "aws"}):
        with patch("metrics_aws.emit_conversion_metrics") as mock_aws:
            metrics.emit_conversion_metrics(5.0, 50_000_000)
            mock_aws.assert_called_once_with(5.0, 50_000_000)


def test_emit_gcp_calls_metrics_gcp() -> None:
    with patch.dict("os.environ", {"METRICS_PROVIDER": "gcp"}):
        with patch("metrics_gcp.emit_conversion_metrics") as mock_gcp:
            metrics.emit_conversion_metrics(5.0, 50_000_000)
            mock_gcp.assert_called_once_with(5.0, 50_000_000)


def test_emit_default_aws_when_unset() -> None:
    with patch.dict("os.environ", {}, clear=False):
        if "METRICS_PROVIDER" in __import__("os").environ:
            del __import__("os").environ["METRICS_PROVIDER"]
    with patch("metrics_aws.emit_conversion_metrics") as mock_aws:
        metrics.emit_conversion_metrics(1.0, 1_000_000)
        mock_aws.assert_called_once_with(1.0, 1_000_000)
