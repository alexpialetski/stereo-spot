"""DynamoDB implementations of JobStore, SegmentCompletionStore, and ReassemblyTriggered lock."""

import time
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from stereo_spot_shared import Job, JobListItem, JobStatus, SegmentCompletion, StereoMode


def _job_to_item(job: Job) -> dict[str, Any]:
    """Convert Job to DynamoDB item (native types for resource API)."""
    d = job.model_dump(mode="json")
    return {k: v for k, v in d.items() if v is not None}


def _item_to_job(item: dict[str, Any]) -> Job:
    """Convert DynamoDB item to Job."""
    return Job.model_validate(item)


def _completion_to_item(completion: SegmentCompletion) -> dict[str, Any]:
    """Convert SegmentCompletion to DynamoDB item."""
    d = completion.model_dump(mode="json")
    return {k: v for k, v in d.items() if v is not None}


def _item_to_completion(item: dict[str, Any]) -> SegmentCompletion:
    """Convert DynamoDB item to SegmentCompletion."""
    return SegmentCompletion.model_validate(item)


class DynamoDBJobStore:
    """JobStore: DynamoDB Jobs table with status-completed_at and status-created_at GSIs."""

    GSI_COMPLETED = "status-completed_at"
    GSI_CREATED = "status-created_at"

    def __init__(
        self,
        table_name: str,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._table_name = table_name
        self._client = boto3.client(
            "dynamodb",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        self._resource = boto3.resource(
            "dynamodb",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        self._table = self._resource.Table(table_name)

    def get(self, job_id: str, *, consistent_read: bool = False) -> Job | None:
        """Return the job if it exists, otherwise None. Use consistent_read=True for progress/SSE so completion is seen promptly."""
        resp = self._table.get_item(
            Key={"job_id": job_id},
            ConsistentRead=consistent_read,
        )
        item = resp.get("Item")
        if not item:
            return None
        return _item_to_job(item)

    def put(self, job: Job) -> None:
        """Create or overwrite a job record."""
        self._table.put_item(Item=_job_to_item(job))

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        total_segments: int | None = None,
        completed_at: int | None = None,
    ) -> None:
        """Update selected attributes of a job by job_id."""
        updates: list[str] = []
        expr_names: dict[str, str] = {}
        expr_values: dict[str, Any] = {}

        if status is not None:
            updates.append("#st = :st")
            expr_names["#st"] = "status"
            expr_values[":st"] = status
        if total_segments is not None:
            updates.append("#ts = :ts")
            expr_names["#ts"] = "total_segments"
            expr_values[":ts"] = total_segments
        if completed_at is not None:
            updates.append("#ca = :ca")
            expr_names["#ca"] = "completed_at"
            expr_values[":ca"] = completed_at

        if not updates:
            return

        self._table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET " + ", ".join(updates),
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )

    def list_completed(
        self,
        limit: int,
        exclusive_start_key: dict[str, Any] | None = None,
    ) -> tuple[list[JobListItem], dict[str, Any] | None]:
        """List jobs with status=completed, ordered by completed_at descending."""
        params: dict[str, Any] = {
            "IndexName": self.GSI_COMPLETED,
            "KeyConditionExpression": Key("status").eq(JobStatus.COMPLETED.value),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if exclusive_start_key:
            params["ExclusiveStartKey"] = exclusive_start_key

        resp = self._table.query(**params)
        items = [
            JobListItem(
                job_id=row["job_id"],
                mode=StereoMode(row["mode"]),
                completed_at=int(row["completed_at"]),
            )
            for row in resp.get("Items", [])
        ]
        next_key = resp.get("LastEvaluatedKey")
        return (items, next_key if next_key else None)

    def list_in_progress(self, limit: int = 20) -> list[Job]:
        """List in-progress jobs (including failed) by created_at desc."""
        statuses = [
            JobStatus.CREATED.value,
            JobStatus.CHUNKING_IN_PROGRESS.value,
            JobStatus.CHUNKING_COMPLETE.value,
            JobStatus.FAILED.value,
        ]
        merged: list[Job] = []
        per_status = max(limit, 7)  # fetch enough per partition to merge
        for status in statuses:
            resp = self._table.query(
                IndexName=self.GSI_CREATED,
                KeyConditionExpression=Key("status").eq(status),
                ScanIndexForward=False,
                Limit=per_status,
            )
            for row in resp.get("Items", []):
                merged.append(_item_to_job(row))
        merged.sort(key=lambda j: j.created_at or 0, reverse=True)
        return merged[:limit]


class DynamoSegmentCompletionStore:
    """SegmentCompletionStore implementation using DynamoDB SegmentCompletions table."""

    def __init__(
        self,
        table_name: str,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._table_name = table_name
        self._resource = boto3.resource(
            "dynamodb",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        self._table = self._resource.Table(table_name)

    def put(self, completion: SegmentCompletion) -> None:
        """Write a segment completion record."""
        self._table.put_item(Item=_completion_to_item(completion))

    def query_by_job(self, job_id: str) -> list[SegmentCompletion]:
        """Return all completions for the job, ordered by segment_index ascending."""
        resp = self._table.query(
            KeyConditionExpression=Key("job_id").eq(job_id),
            ScanIndexForward=True,
        )
        return [_item_to_completion(row) for row in resp.get("Items", [])]


class ReassemblyTriggeredLock:
    """
    ReassemblyTriggered table: used for idempotency (Lambda conditional create)
    and media-worker lock (conditional update: set reassembly_started_at
    only if item exists and that attribute is absent).
    """

    def __init__(
        self,
        table_name: str,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._table_name = table_name
        self._resource = boto3.resource(
            "dynamodb",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        self._table = self._resource.Table(table_name)

    def try_acquire(self, job_id: str) -> bool:
        """
        Try to acquire the reassembly lock for this job.

        Performs a conditional update: SET reassembly_started_at = now()
        only if the item exists AND attribute_not_exists(reassembly_started_at).
        Returns True if the update succeeded (this worker won the lock),
        False if another worker already started or the item does not exist.
        """
        try:
            self._table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET reassembly_started_at = :now",
                ConditionExpression=(
                    "attribute_exists(job_id) AND attribute_not_exists(reassembly_started_at)"
                ),
                ExpressionAttributeValues={":now": int(time.time())},
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def try_create_triggered(self, job_id: str) -> bool:
        """
        Create ReassemblyTriggered item only if job_id does not exist (conditional create).
        Sets triggered_at (Unix now) and ttl (now + 90 days) for TTL cleanup.
        Returns True if put succeeded, False if item already exists (idempotent).
        """
        now = int(time.time())
        ttl = now + (90 * 86400)
        try:
            self._table.put_item(
                Item={
                    "job_id": job_id,
                    "triggered_at": now,
                    "ttl": ttl,
                },
                ConditionExpression="attribute_not_exists(job_id)",
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
