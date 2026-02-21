"""
Build AWS adapter instances from environment variables.

Use when deploying with Terraform: Terraform outputs (e.g. queue URLs, bucket names,
table names) are passed into the process as env vars. Set these before constructing
adapters so resource names are not hardcoded.

Required env vars (match Terraform output names, uppercased with underscores):
- INPUT_BUCKET_NAME
- OUTPUT_BUCKET_NAME
- JOBS_TABLE_NAME
- SEGMENT_COMPLETIONS_TABLE_NAME
- REASSEMBLY_TRIGGERED_TABLE_NAME
- CHUNKING_QUEUE_URL
- VIDEO_WORKER_QUEUE_URL
- SEGMENT_OUTPUT_QUEUE_URL (video-worker segment-output queue)
- REASSEMBLY_QUEUE_URL
- DELETION_QUEUE_URL (web-ui and media-worker)

Optional:
- AWS_REGION (default: us-east-1)
- AWS_ENDPOINT_URL (e.g. for LocalStack)
- SQS_LONG_POLL_WAIT_SECONDS (default: 20, max 20) for receive long polling
- NAME_PREFIX (e.g. stereo-spot): when set, operator_links_from_env() returns a provider for
  CloudWatch Logs Insights and Cost Explorer links.
- LOGS_REGION: region for log links (default: AWS_REGION or us-east-1).
- COST_EXPLORER_URL: optional override for the Cost Explorer deep link (default: App-tag filter).
"""

import os

from stereo_spot_shared.interfaces import OperatorLinksProvider

from .dynamodb_stores import (
    DynamoDBJobStore,
    DynamoSegmentCompletionStore,
    ReassemblyTriggeredLock,
)
from .operator_links import AWSOperatorLinksProvider
from .s3_storage import S3ObjectStorage
from .sqs_queues import SQSQueueReceiver, SQSQueueSender


def _sqs_wait_time_seconds() -> int:
    """Long-poll wait time for SQS receive (0-20). Default 20 for responsive pickup."""
    val = os.environ.get("SQS_LONG_POLL_WAIT_SECONDS", "20")
    return min(20, max(0, int(val)))


def _get_region() -> str | None:
    return os.environ.get("AWS_REGION") or None


def _get_endpoint_url() -> str | None:
    return os.environ.get("AWS_ENDPOINT_URL") or None


def job_store_from_env() -> DynamoDBJobStore:
    """Build DynamoDBJobStore from JOBS_TABLE_NAME."""
    table_name = os.environ["JOBS_TABLE_NAME"]
    return DynamoDBJobStore(
        table_name,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
    )


def segment_completion_store_from_env() -> DynamoSegmentCompletionStore:
    """Build DynamoSegmentCompletionStore from SEGMENT_COMPLETIONS_TABLE_NAME."""
    table_name = os.environ["SEGMENT_COMPLETIONS_TABLE_NAME"]
    return DynamoSegmentCompletionStore(
        table_name,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
    )


def chunking_queue_sender_from_env() -> SQSQueueSender:
    """Build SQSQueueSender for chunking queue from CHUNKING_QUEUE_URL."""
    url = os.environ["CHUNKING_QUEUE_URL"]
    return SQSQueueSender(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
    )


def chunking_queue_receiver_from_env() -> SQSQueueReceiver:
    """Build SQSQueueReceiver for chunking queue from CHUNKING_QUEUE_URL."""
    url = os.environ["CHUNKING_QUEUE_URL"]
    return SQSQueueReceiver(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
        wait_time_seconds=_sqs_wait_time_seconds(),
    )


def video_worker_queue_sender_from_env() -> SQSQueueSender:
    """Build SQSQueueSender for video-worker queue from VIDEO_WORKER_QUEUE_URL."""
    url = os.environ["VIDEO_WORKER_QUEUE_URL"]
    return SQSQueueSender(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
    )


def video_worker_queue_receiver_from_env() -> SQSQueueReceiver:
    """Build SQSQueueReceiver for video-worker queue from VIDEO_WORKER_QUEUE_URL."""
    url = os.environ["VIDEO_WORKER_QUEUE_URL"]
    return SQSQueueReceiver(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
        wait_time_seconds=_sqs_wait_time_seconds(),
    )


def segment_output_queue_receiver_from_env() -> SQSQueueReceiver:
    """Build SQSQueueReceiver for segment-output queue from SEGMENT_OUTPUT_QUEUE_URL."""
    url = os.environ["SEGMENT_OUTPUT_QUEUE_URL"]
    return SQSQueueReceiver(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
        wait_time_seconds=_sqs_wait_time_seconds(),
    )


def reassembly_triggered_lock_from_env() -> ReassemblyTriggeredLock:
    """Build ReassemblyTriggeredLock from REASSEMBLY_TRIGGERED_TABLE_NAME."""
    table_name = os.environ["REASSEMBLY_TRIGGERED_TABLE_NAME"]
    return ReassemblyTriggeredLock(
        table_name,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
    )


def reassembly_queue_sender_from_env() -> SQSQueueSender:
    """Build SQSQueueSender for reassembly queue from REASSEMBLY_QUEUE_URL."""
    url = os.environ["REASSEMBLY_QUEUE_URL"]
    return SQSQueueSender(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
    )


def reassembly_queue_receiver_from_env() -> SQSQueueReceiver:
    """Build SQSQueueReceiver for reassembly queue from REASSEMBLY_QUEUE_URL."""
    url = os.environ["REASSEMBLY_QUEUE_URL"]
    return SQSQueueReceiver(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
        wait_time_seconds=_sqs_wait_time_seconds(),
    )


def deletion_queue_sender_from_env() -> SQSQueueSender:
    """Build SQSQueueSender for deletion queue from DELETION_QUEUE_URL."""
    url = os.environ["DELETION_QUEUE_URL"]
    return SQSQueueSender(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
    )


def deletion_queue_receiver_from_env() -> SQSQueueReceiver:
    """Build SQSQueueReceiver for deletion queue from DELETION_QUEUE_URL."""
    url = os.environ["DELETION_QUEUE_URL"]
    return SQSQueueReceiver(
        url,
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
        wait_time_seconds=_sqs_wait_time_seconds(),
    )


def object_storage_from_env() -> S3ObjectStorage:
    """Build S3ObjectStorage (uses default credentials; bucket names come from callers)."""
    return S3ObjectStorage(
        region_name=_get_region(),
        endpoint_url=_get_endpoint_url(),
    )


def input_bucket_name() -> str:
    """Return input bucket name from INPUT_BUCKET_NAME."""
    return os.environ["INPUT_BUCKET_NAME"]


def output_bucket_name() -> str:
    """Return output bucket name from OUTPUT_BUCKET_NAME."""
    return os.environ["OUTPUT_BUCKET_NAME"]


def operator_links_from_env() -> OperatorLinksProvider | None:
    """
    Build AWS operator links provider when NAME_PREFIX is set (e.g. ECS deployment).
    Returns None when NAME_PREFIX is unset so the web-ui does not show AWS console links.
    """
    name_prefix = os.environ.get("NAME_PREFIX")
    if not name_prefix:
        return None
    region = (
        os.environ.get("LOGS_REGION")
        or os.environ.get("AWS_REGION")
        or "us-east-1"
    )
    cost_url = os.environ.get("COST_EXPLORER_URL") or None
    return AWSOperatorLinksProvider(
        name_prefix=name_prefix,
        region=region,
        cost_explorer_url=cost_url,
    )
