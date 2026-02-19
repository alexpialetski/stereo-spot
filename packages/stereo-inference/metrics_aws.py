"""AWS CloudWatch metrics adapter. Emits StereoSpot/Conversion metrics. Bucket boundaries must match aws-adapters SEGMENT_SIZE_BUCKETS."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _segment_size_bucket(size_mb: float) -> str:
    if size_mb <= 0:
        return "0-5"
    if size_mb < 5:
        return "0-5"
    if size_mb < 20:
        return "5-20"
    if size_mb < 50:
        return "20-50"
    return "50+"


def emit_conversion_metrics(duration_seconds: float, size_bytes: int) -> None:
    import boto3
    try:
        namespace = os.environ.get("METRICS_NAMESPACE", "StereoSpot/Conversion")
        cloud_name = os.environ.get("ETA_CLOUD_NAME", "aws")
        size_mb = size_bytes / 1e6
        bucket = _segment_size_bucket(size_mb)
        dimensions = [
            {"Name": "Cloud", "Value": cloud_name},
            {"Name": "SegmentSizeBucket", "Value": bucket},
        ]
        metric_data = [
            {
                "MetricName": "SegmentConversionDurationSeconds",
                "Value": duration_seconds,
                "Unit": "Seconds",
                "Dimensions": dimensions,
            },
        ]
        if size_mb > 0:
            conversion_seconds_per_mb = duration_seconds / size_mb
            metric_data.append(
                {
                    "MetricName": "ConversionSecondsPerMb",
                    "Value": conversion_seconds_per_mb,
                    "Unit": "None",
                    "Dimensions": dimensions,
                }
            )
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        cw = boto3.client("cloudwatch", region_name=region) if region else boto3.client("cloudwatch")
        cw.put_metric_data(Namespace=namespace, MetricData=metric_data)
    except Exception as e:
        logger.warning("Failed to put CloudWatch metrics: %s", e)
