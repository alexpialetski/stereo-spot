"""
Cloud-agnostic interfaces for job store, segment-completion store, queues,
object storage, and analytics.

Implementations (e.g. AWS via DynamoDB, SQS, S3, CloudWatch) live in
separate packages (e.g. aws-adapters). Pipeline logic depends on these
interfaces and receives the implementation by config.
"""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .models import AnalyticsSnapshot, Job, JobListItem, SegmentCompletion


@runtime_checkable
class JobStore(Protocol):
    """Store for job records (get, put, update by job_id; list completed with pagination)."""

    def get(self, job_id: str, *, consistent_read: bool = False) -> Job | None:
        """Return the job if it exists, otherwise None.
        Use consistent_read=True for progress/SSE so completion is seen promptly."""
        ...

    def put(self, job: Job) -> None:
        """Create or overwrite a job record."""
        ...

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        total_segments: int | None = None,
        completed_at: int | None = None,
    ) -> None:
        """Update selected attributes of a job by job_id."""
        ...

    def list_completed(
        self,
        limit: int,
        exclusive_start_key: dict[str, Any] | None = None,
    ) -> tuple[list[JobListItem], dict[str, Any] | None]:
        """
        List jobs with status=completed, ordered by completed_at descending.

        Returns (items, next_exclusive_start_key). next_exclusive_start_key is non-None
        when there are more pages.
        """
        ...

    def list_in_progress(self, limit: int = 20) -> list[Job]:
        """
        List jobs with status in (created, chunking_in_progress, chunking_complete, failed),
        ordered by created_at descending. Returns up to limit items.
        """
        ...


@runtime_checkable
class SegmentCompletionStore(Protocol):
    """Store for segment completion records (put; query by job_id ordered by segment_index)."""

    def put(self, completion: SegmentCompletion) -> None:
        """Write a segment completion record."""
        ...

    def query_by_job(self, job_id: str) -> list[SegmentCompletion]:
        """Return all completions for the job, ordered by segment_index ascending."""
        ...


class QueueMessage:
    """A message received from a queue (body + receipt handle for delete)."""

    def __init__(self, receipt_handle: str, body: str | bytes) -> None:
        self.receipt_handle = receipt_handle
        self.body = body


@runtime_checkable
class QueueSender(Protocol):
    """Send messages to a queue."""

    def send(self, body: str | bytes) -> None:
        """Send one message with the given body."""
        ...


@runtime_checkable
class QueueReceiver(Protocol):
    """Receive and delete messages from a queue."""

    def receive(self, max_messages: int = 1) -> list[QueueMessage]:
        """Receive up to max_messages. Returns empty list if none available."""
        ...

    def delete(self, receipt_handle: str) -> None:
        """Delete a message by its receipt handle after successful processing."""
        ...


@runtime_checkable
class ObjectStorage(Protocol):
    """Object storage: presign upload/download URLs and upload/download bytes."""

    def presign_upload(
        self,
        bucket: str,
        key: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned PUT URL for the given bucket and key."""
        ...

    def presign_download(
        self,
        bucket: str,
        key: str,
        *,
        expires_in: int = 3600,
        response_content_disposition: str | None = None,
    ) -> str:
        """Return presigned GET URL. Use response_content_disposition for download."""
        ...

    def upload(self, bucket: str, key: str, body: bytes) -> None:
        """Upload bytes to the given bucket and key."""
        ...

    def upload_file(self, bucket: str, key: str, path: str) -> None:
        """Upload a file from local path to bucket/key. May use multipart for large files."""
        ...

    def exists(self, bucket: str, key: str) -> bool:
        """Return True if the object exists, False otherwise."""
        ...

    def download(self, bucket: str, key: str) -> bytes:
        """Download object from bucket/key and return its body as bytes."""
        ...


@runtime_checkable
class ConversionMetricsProvider(Protocol):
    """Provider for conversion metrics (e.g. CloudWatch, Cloud Monitoring)."""

    def get_conversion_metrics(
        self,
        start_time: datetime,
        end_time: datetime,
        period_seconds: int,
        *,
        region: str | None = None,
        endpoint_name: str | None = None,
        cloud_name: str = "aws",
    ) -> AnalyticsSnapshot:
        """Fetch conversion metrics for the given time range and return a snapshot."""
        ...
