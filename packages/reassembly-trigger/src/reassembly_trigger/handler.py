"""
Lambda handler for DynamoDB Stream (SegmentCompletions).

For each batch, for each distinct job_id in the batch, check that Job has
status=chunking_complete and count(SegmentCompletions)==total_segments.
If so, conditional create on ReassemblyTriggered; on success send job_id to reassembly queue.
"""

import json
import os
import time
from collections.abc import Sequence

import boto3
from botocore.exceptions import ClientError

# shared-types bundled in layer/deployment package
from stereo_spot_shared import Job, JobStatus, ReassemblyPayload


def _get_job_ids_from_stream_records(records: Sequence[dict]) -> set[str]:
    """Extract distinct job_id from DynamoDB Stream records (Keys.job_id)."""
    job_ids: set[str] = set()
    for record in records:
        dynamodb = record.get("dynamodb") or {}
        keys = dynamodb.get("Keys") or {}
        job_id_val = keys.get("job_id")
        if job_id_val and "S" in job_id_val:
            job_ids.add(job_id_val["S"])
    return job_ids


def _get_job(
    jobs_table: str,
    job_id: str,
    *,
    dynamodb_client=None,
) -> dict | None:
    """Get Job item from DynamoDB; return raw item or None."""
    client = dynamodb_client or boto3.client("dynamodb")
    resp = client.get_item(
        TableName=jobs_table,
        Key={"job_id": {"S": job_id}},
    )
    item = resp.get("Item")
    if not item:
        return None
    # Unmarshall to plain dict for Job.model_validate
    return _unmarshall(item)


def _unmarshall(d: dict) -> dict:
    """Simple unmarshall of DynamoDB item to Python types (S, N, NULL)."""
    out: dict = {}
    for k, v in d.items():
        if "S" in v:
            out[k] = v["S"]
        elif "N" in v:
            out[k] = int(v["N"])
        elif "NULL" in v:
            out[k] = None
        else:
            out[k] = v
    return out


def _count_segment_completions(
    segment_completions_table: str,
    job_id: str,
    *,
    dynamodb_client=None,
) -> int:
    """Return count of SegmentCompletions for job_id (query by PK)."""
    client = dynamodb_client or boto3.client("dynamodb")
    resp = client.query(
        TableName=segment_completions_table,
        KeyConditionExpression="job_id = :jid",
        ExpressionAttributeValues={":jid": {"S": job_id}},
        Select="COUNT",
    )
    return resp.get("Count", 0)


def _conditional_create_reassembly_triggered(
    reassembly_triggered_table: str,
    job_id: str,
    *,
    dynamodb_client=None,
) -> bool:
    """
    Put item only if job_id does not exist (conditional create).
    Set triggered_at and ttl (90 days for TTL cleanup).
    Returns True if put succeeded, False if condition failed (already exists).
    """
    client = dynamodb_client or boto3.client("dynamodb")
    now = int(time.time())
    ttl = now + (90 * 86400)
    try:
        client.put_item(
            TableName=reassembly_triggered_table,
            Item={
                "job_id": {"S": job_id},
                "triggered_at": {"N": str(now)},
                "ttl": {"N": str(ttl)},
            },
            ConditionExpression="attribute_not_exists(job_id)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _send_reassembly_message(
    queue_url: str,
    job_id: str,
    *,
    sqs_client=None,
) -> None:
    """Send ReassemblyPayload (job_id) to reassembly queue."""
    client = sqs_client or boto3.client("sqs")
    body = ReassemblyPayload(job_id=job_id).model_dump_json()
    client.send_message(QueueUrl=queue_url, MessageBody=body)


def should_trigger_reassembly(
    jobs_table: str,
    segment_completions_table: str,
    job_id: str,
    *,
    dynamodb_client=None,
) -> bool:
    """
    Return True if job has status=chunking_complete and
    count(SegmentCompletions for job_id) == job.total_segments.
    """
    job_item = _get_job(jobs_table, job_id, dynamodb_client=dynamodb_client)
    if not job_item:
        return False
    try:
        job = Job.model_validate(job_item)
    except Exception:
        return False
    if job.status != JobStatus.CHUNKING_COMPLETE:
        return False
    if job.total_segments is None or job.total_segments < 1:
        return False
    count = _count_segment_completions(
        segment_completions_table, job_id, dynamodb_client=dynamodb_client
    )
    return count == job.total_segments


def process_job_id(
    job_id: str,
    jobs_table: str,
    segment_completions_table: str,
    reassembly_triggered_table: str,
    reassembly_queue_url: str,
    *,
    dynamodb_client=None,
    sqs_client=None,
) -> None:
    """
    If should_trigger_reassembly: conditional create ReassemblyTriggered;
    if create succeeded, send job_id to reassembly queue.
    """
    if not should_trigger_reassembly(
        jobs_table,
        segment_completions_table,
        job_id,
        dynamodb_client=dynamodb_client,
    ):
        return
    created = _conditional_create_reassembly_triggered(
        reassembly_triggered_table,
        job_id,
        dynamodb_client=dynamodb_client,
    )
    if created:
        _send_reassembly_message(
            reassembly_queue_url,
            job_id,
            sqs_client=sqs_client,
        )


def lambda_handler(event: dict, context: object) -> dict:
    """
    DynamoDB Stream handler for SegmentCompletions table.

    Env vars (set by Terraform): JOBS_TABLE_NAME, SEGMENT_COMPLETIONS_TABLE_NAME,
    REASSEMBLY_TRIGGERED_TABLE_NAME, REASSEMBLY_QUEUE_URL.
    """
    jobs_table = os.environ["JOBS_TABLE_NAME"]
    segment_completions_table = os.environ["SEGMENT_COMPLETIONS_TABLE_NAME"]
    reassembly_triggered_table = os.environ["REASSEMBLY_TRIGGERED_TABLE_NAME"]
    reassembly_queue_url = os.environ["REASSEMBLY_QUEUE_URL"]

    records = event.get("Records") or []
    job_ids = _get_job_ids_from_stream_records(records)

    dynamodb_client = boto3.client("dynamodb")
    sqs_client = boto3.client("sqs")

    for job_id in job_ids:
        try:
            process_job_id(
                job_id,
                jobs_table,
                segment_completions_table,
                reassembly_triggered_table,
                reassembly_queue_url,
                dynamodb_client=dynamodb_client,
                sqs_client=sqs_client,
            )
        except Exception:
            # Let Lambda retry the batch
            raise

    return {"statusCode": 200, "body": json.dumps({"processed_job_ids": list(job_ids)})}
