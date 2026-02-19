"""CloudWatch metrics for StereoSpot conversion analytics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from stereo_spot_shared import AnalyticsSnapshot


def _to_json_safe(obj: object) -> object:
    """Convert boto3 response to JSON-serializable types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    return obj


def get_conversion_metrics(
    start_time: datetime,
    end_time: datetime,
    period_seconds: int,
    *,
    region: str | None = None,
    endpoint_name: str | None = None,
    cloud_name: str = "aws",
) -> AnalyticsSnapshot:
    """
    Fetch conversion metrics from CloudWatch for the given time range.

    Uses AWS/SageMaker (ModelLatency, TotalProcessingTime) when endpoint_name is set,
    and StereoSpot/Conversion (SegmentConversionDurationSeconds) in all cases.
    """
    import boto3

    region = region or "us-east-1"
    metrics: dict[str, object] = {}
    cw = boto3.client("cloudwatch", region_name=region)

    if endpoint_name:
        for namespace, metric_name, dimensions in [
            (
                "AWS/SageMaker",
                "ModelLatency",
                [
                    {"Name": "EndpointName", "Value": endpoint_name},
                    {"Name": "VariantName", "Value": "AllTraffic"},
                ],
            ),
            (
                "AWS/SageMaker",
                "TotalProcessingTime",
                [
                    {"Name": "EndpointName", "Value": endpoint_name},
                    {"Name": "VariantName", "Value": "AllTraffic"},
                ],
            ),
        ]:
            try:
                r = cw.get_metric_statistics(
                    Namespace=namespace,
                    MetricName=metric_name,
                    Dimensions=dimensions,
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=period_seconds,
                    Statistics=["Average", "SampleCount", "Maximum", "Minimum"],
                )
                metrics[metric_name] = _to_json_safe(r)
            except Exception as e:
                metrics[metric_name] = {"error": str(e)}

    try:
        r = cw.get_metric_statistics(
            Namespace="StereoSpot/Conversion",
            MetricName="SegmentConversionDurationSeconds",
            Dimensions=[{"Name": "Cloud", "Value": cloud_name}],
            StartTime=start_time,
            EndTime=end_time,
            Period=period_seconds,
            Statistics=["Average", "SampleCount", "Maximum", "Minimum"],
        )
        metrics["SegmentConversionDurationSeconds"] = _to_json_safe(r)
    except Exception as e:
        metrics["SegmentConversionDurationSeconds"] = {"error": str(e)}

    return AnalyticsSnapshot(
        timestamp=end_time.isoformat(),
        cloud=cloud_name,
        endpoint_name=endpoint_name,
        region=region,
        period_hours=(end_time - start_time).total_seconds() / 3600.0,
        metrics=metrics,
        log_summary=None,
    )
