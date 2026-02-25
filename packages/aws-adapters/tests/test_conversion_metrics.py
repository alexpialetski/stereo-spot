"""Tests for AWS CloudWatch conversion metrics: bucket boundaries and emit."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from stereo_spot_aws_adapters import conversion_metrics


def test_segment_size_bucket_0_5() -> None:
    assert conversion_metrics._segment_size_bucket(0) == "0-5"
    assert conversion_metrics._segment_size_bucket(0.1) == "0-5"
    assert conversion_metrics._segment_size_bucket(4.9) == "0-5"


def test_segment_size_bucket_5_20() -> None:
    assert conversion_metrics._segment_size_bucket(5) == "5-20"
    assert conversion_metrics._segment_size_bucket(10) == "5-20"
    assert conversion_metrics._segment_size_bucket(19.9) == "5-20"


def test_segment_size_bucket_20_50() -> None:
    assert conversion_metrics._segment_size_bucket(20) == "20-50"
    assert conversion_metrics._segment_size_bucket(35) == "20-50"
    assert conversion_metrics._segment_size_bucket(49.9) == "20-50"


def test_segment_size_bucket_50_plus() -> None:
    assert conversion_metrics._segment_size_bucket(50) == "50+"
    assert conversion_metrics._segment_size_bucket(100) == "50+"


def test_emit_conversion_metrics_calls_put_metric_data() -> None:
    mock_cw = MagicMock()
    emitter = conversion_metrics.CloudWatchConversionMetricsEmitter()
    with patch("boto3.client", return_value=mock_cw):
        emitter.emit_conversion_metrics(77.5, 50_000_000)
    mock_cw.put_metric_data.assert_called_once()
    call = mock_cw.put_metric_data.call_args
    assert call.kwargs["Namespace"] == "StereoSpot/Conversion"
    metric_data = call.kwargs["MetricData"]
    assert len(metric_data) >= 1
    names = [m["MetricName"] for m in metric_data]
    assert "SegmentConversionDurationSeconds" in names
    assert "ConversionSecondsPerMb" in names
    for m in metric_data:
        dims = {d["Name"]: d["Value"] for d in m["Dimensions"]}
        assert dims.get("SegmentSizeBucket") == "50+"
