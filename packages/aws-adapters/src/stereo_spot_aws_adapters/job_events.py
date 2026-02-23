"""
Job-events bridge adapter for AWS: normalizer (DynamoDB stream -> normalized event),
JobEventsSink (SQS), and get_aws_adapter() for Lambda handler.
"""

import os
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer
from stereo_spot_shared import JobEvent, JobTableChange, SegmentCompletionInsert

from .dynamodb_stores import DynamoDBJobStore, DynamoSegmentCompletionStore
from .sqs_queues import SQSQueueSender

_deserializer = TypeDeserializer()


def _unmarshall_dynamodb_item(item: dict[str, Any]) -> dict[str, Any]:
    """Convert DynamoDB wire format to native Python dict (ints for numeric job fields)."""
    if not item:
        return {}
    result = _deserializer.deserialize({"M": item})
    assert isinstance(result, dict)
    # DynamoDB N type -> Decimal; Job expects int for timestamps and counts
    int_keys = {
        "created_at", "completed_at", "uploaded_at",
        "total_segments", "segment_index", "source_file_size_bytes",
    }
    for key in int_keys:
        if key in result and result[key] is not None:
            val = result[key]
            if isinstance(val, Decimal):
                result[key] = int(val)
    return result


def normalize_dynamodb_stream_record(
    record: dict[str, Any],
    *,
    jobs_stream_arn: str | None = None,
    segment_completions_stream_arn: str | None = None,
) -> JobTableChange | SegmentCompletionInsert | None:
    """
    Parse a DynamoDB stream record into a normalized event.
    Uses eventSourceARN to distinguish jobs table vs segment_completions table.
    """
    arn = record.get("eventSourceARN") or ""
    event_name = record.get("eventName")
    dynamodb = record.get("dynamodb") or {}
    new_image = dynamodb.get("NewImage")
    if not new_image:
        return None

    if jobs_stream_arn and arn == jobs_stream_arn:
        unmarshalled = _unmarshall_dynamodb_item(new_image)
        job_id = unmarshalled.get("job_id")
        if not job_id:
            return None
        return JobTableChange(job_id=job_id, new_image=unmarshalled)

    if segment_completions_stream_arn and arn == segment_completions_stream_arn:
        if event_name != "INSERT":
            return None
        unmarshalled = _unmarshall_dynamodb_item(new_image)
        job_id = unmarshalled.get("job_id")
        segment_index = unmarshalled.get("segment_index")
        if job_id is None or segment_index is None:
            return None
        return SegmentCompletionInsert(job_id=job_id, segment_index=int(segment_index))

    return None


def job_events_normalizer_from_env() -> Callable[
    [dict[str, Any]], JobTableChange | SegmentCompletionInsert | None
]:
    """
    Return a normalizer that reads stream ARNs from env (JOBS_TABLE_*, SEGMENT_COMPLETIONS_*).
    Used by web-ui consumer for stream records from the job-events queue (EventBridge Pipes).
    """
    jobs_stream_arn = os.environ.get("JOBS_TABLE_STREAM_ARN") or None
    segment_stream_arn = os.environ.get("SEGMENT_COMPLETIONS_TABLE_STREAM_ARN") or None

    def normalizer(record: dict[str, Any]) -> JobTableChange | SegmentCompletionInsert | None:
        return normalize_dynamodb_stream_record(
            record,
            jobs_stream_arn=jobs_stream_arn,
            segment_completions_stream_arn=segment_stream_arn,
        )

    return normalizer


class SQSJobEventsSink:
    """Send JobEvent to job-events SQS queue."""

    def __init__(self, queue_url: str, *, region_name: str | None = None) -> None:
        self._sender = SQSQueueSender(queue_url, region_name=region_name)

    def send(self, job_event: JobEvent) -> None:
        """Serialize and send one job event."""
        self._sender.send(job_event.model_dump_json())


def get_aws_adapter() -> Any:
    """
    Return adapter object for the bridge handler: normalizer, job_store, segment_store, sink.
    Reads config from env: JOB_EVENTS_QUEUE_URL, JOBS_TABLE_NAME, SEGMENT_COMPLETIONS_TABLE_NAME,
    JOBS_TABLE_STREAM_ARN, SEGMENT_COMPLETIONS_TABLE_STREAM_ARN, AWS_REGION.
    """
    queue_url = os.environ["JOB_EVENTS_QUEUE_URL"]
    jobs_table = os.environ.get("JOBS_TABLE_NAME", "")
    segment_table = os.environ.get("SEGMENT_COMPLETIONS_TABLE_NAME", "")
    jobs_stream_arn = os.environ.get("JOBS_TABLE_STREAM_ARN") or None
    segment_stream_arn = os.environ.get("SEGMENT_COMPLETIONS_TABLE_STREAM_ARN") or None
    region = os.environ.get("AWS_REGION")

    job_store = DynamoDBJobStore(jobs_table, region_name=region)
    segment_store = DynamoSegmentCompletionStore(segment_table, region_name=region)
    sink = SQSJobEventsSink(queue_url, region_name=region)

    def normalizer(record: dict[str, Any]) -> JobTableChange | SegmentCompletionInsert | None:
        return normalize_dynamodb_stream_record(
            record,
            jobs_stream_arn=jobs_stream_arn,
            segment_completions_stream_arn=segment_stream_arn,
        )

    class Adapter:
        def __init__(self, normalizer, job_store, segment_store, sink):
            self.normalizer = normalizer
            self.job_store = job_store
            self.segment_store = segment_store
            self.sink = sink

    return Adapter(normalizer, job_store, segment_store, sink)
