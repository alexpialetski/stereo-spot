"""CloudWatch metrics for StereoSpot conversion analytics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from stereo_spot_shared import AnalyticsSnapshot

# Must match stereocrafter-sagemaker serve._segment_size_bucket buckets
SEGMENT_SIZE_BUCKETS = ["0-5", "5-20", "20-50", "50+"]


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


def _weighted_avg_from_datapoints(datapoints: list[dict]) -> float | None:
    """Compute weighted average from get_metric_statistics Datapoints (Average * SampleCount / sum(SampleCount)). Returns None if no data."""
    total_weight = 0.0
    weighted_sum = 0.0
    for dp in datapoints:
        avg = dp.get("Average")
        count = dp.get("SampleCount")
        if avg is not None and count is not None and count > 0:
            total_weight += float(count)
            weighted_sum += float(avg) * float(count)
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


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

    # Legacy: SegmentConversionDurationSeconds with Cloud only (fallback when endpoint has no SegmentSizeBucket)
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

    # Per-bucket metrics (Cloud + SegmentSizeBucket); same dimension set required to get data
    base_dims = [{"Name": "Cloud", "Value": cloud_name}]
    duration_by_bucket: dict[str, object] = {}
    conversion_per_mb_by_bucket: dict[str, object] = {}
    all_conversion_datapoints: list[dict] = []

    for bucket in SEGMENT_SIZE_BUCKETS:
        dimensions = base_dims + [{"Name": "SegmentSizeBucket", "Value": bucket}]
        for metric_name, out_key in [
            ("SegmentConversionDurationSeconds", duration_by_bucket),
            ("ConversionSecondsPerMb", conversion_per_mb_by_bucket),
        ]:
            try:
                r = cw.get_metric_statistics(
                    Namespace="StereoSpot/Conversion",
                    MetricName=metric_name,
                    Dimensions=dimensions,
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=period_seconds,
                    Statistics=["Average", "SampleCount", "Maximum", "Minimum"],
                )
                out_key[bucket] = _to_json_safe(r)
                if metric_name == "ConversionSecondsPerMb" and isinstance(r.get("Datapoints"), list):
                    all_conversion_datapoints.extend(r["Datapoints"])
            except Exception as e:
                out_key[bucket] = {"error": str(e)}

    if duration_by_bucket:
        metrics["SegmentConversionDurationSeconds_by_bucket"] = duration_by_bucket
    if conversion_per_mb_by_bucket:
        metrics["ConversionSecondsPerMb_by_bucket"] = conversion_per_mb_by_bucket
    overall_avg = _weighted_avg_from_datapoints(all_conversion_datapoints)
    if overall_avg is not None:
        metrics["ConversionSecondsPerMb"] = {"overall_avg": overall_avg}

    return AnalyticsSnapshot(
        timestamp=end_time.isoformat(),
        cloud=cloud_name,
        endpoint_name=endpoint_name,
        region=region,
        period_hours=(end_time - start_time).total_seconds() / 3600.0,
        metrics=metrics,
        log_summary=None,
    )
