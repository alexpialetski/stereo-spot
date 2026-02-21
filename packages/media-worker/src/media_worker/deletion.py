"""
Deletion loop: receive job_id from queue, delete S3 objects and DynamoDB records for the job.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Protocol

from stereo_spot_shared import DeletionPayload, JobStatus
from stereo_spot_shared.interfaces import (
    JobStore,
    ObjectStorage,
    QueueReceiver,
    SegmentCompletionStore,
)

logger = logging.getLogger(__name__)

# Key layout: input/{job_id}/source.mp4, segments/{job_id}/..., jobs/{job_id}/...
INPUT_SOURCE_KEY_TEMPLATE = "input/{job_id}/source.mp4"
INPUT_SEGMENTS_PREFIX_TEMPLATE = "segments/{job_id}/"
OUTPUT_JOB_PREFIX_TEMPLATE = "jobs/{job_id}/"


class ReassemblyLockForDeletion(Protocol):
    """Protocol for lock that supports delete (e.g. ReassemblyTriggeredLock)."""

    def delete(self, job_id: str) -> None:
        """Delete the lock/trigger record for this job."""
        ...


def _parse_deletion_body(body: str | bytes) -> DeletionPayload | None:
    """Parse queue message body as DeletionPayload (JSON with job_id)."""
    try:
        raw = body.decode() if isinstance(body, bytes) else body
        data = json.loads(raw)
        return DeletionPayload.model_validate(data)
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def process_one_deletion_message(
    payload_str: str | bytes,
    job_store: JobStore,
    segment_store: SegmentCompletionStore,
    storage: ObjectStorage,
    reassembly_lock: ReassemblyLockForDeletion,
    input_bucket: str,
    output_bucket: str,
) -> bool:
    """
    Process a single deletion queue message (job_id).

    Deletes: input source, input segments prefix, output job prefix, segment completions,
    reassembly triggered record. Job record remains with status=deleted.

    Returns True if the message was processed (cleanup done or skipped idempotently),
    False if the message should not be deleted (invalid body).
    """
    payload = _parse_deletion_body(payload_str)
    if payload is None:
        logger.warning("deletion: invalid message body")
        return False
    job_id = payload.job_id
    logger.info("deletion: job_id=%s start", job_id)

    job = job_store.get(job_id)
    if job is not None and job.status != JobStatus.DELETED:
        logger.info(
            "deletion: job_id=%s status=%s (not deleted), skipping cleanup",
            job_id,
            job.status.value,
        )
        return True

    # Delete input bucket: source file
    input_source_key = INPUT_SOURCE_KEY_TEMPLATE.format(job_id=job_id)
    try:
        storage.delete(input_bucket, input_source_key)
    except Exception as e:
        logger.warning("deletion: job_id=%s delete input source failed: %s", job_id, e)

    # Delete input bucket: segments prefix
    segments_prefix = INPUT_SEGMENTS_PREFIX_TEMPLATE.format(job_id=job_id)
    for key in storage.list_object_keys(input_bucket, segments_prefix):
        try:
            storage.delete(input_bucket, key)
        except Exception as e:
            logger.warning("deletion: job_id=%s delete input key %s failed: %s", job_id, key, e)

    # Delete output bucket: jobs/{job_id}/ prefix (final.mp4 and segments)
    output_prefix = OUTPUT_JOB_PREFIX_TEMPLATE.format(job_id=job_id)
    for key in storage.list_object_keys(output_bucket, output_prefix):
        try:
            storage.delete(output_bucket, key)
        except Exception as e:
            logger.warning("deletion: job_id=%s delete output key %s failed: %s", job_id, key, e)

    segment_store.delete_by_job(job_id)
    try:
        reassembly_lock.delete(job_id)
    except Exception as e:
        logger.warning("deletion: job_id=%s reassembly_lock.delete failed: %s", job_id, e)

    logger.info("deletion: job_id=%s done", job_id)
    return True


def run_deletion_loop(
    receiver: QueueReceiver,
    job_store: JobStore,
    segment_store: SegmentCompletionStore,
    storage: ObjectStorage,
    reassembly_lock: ReassemblyLockForDeletion,
    input_bucket: str,
    output_bucket: str,
    *,
    poll_interval_sec: float = 5.0,
) -> None:
    """
    Long-running loop: receive messages from deletion queue, process each, delete on success.
    """
    logger.info("deletion loop started")
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("deletion: received %s message(s)", len(messages))
        for msg in messages:
            body = msg.body
            try:
                ok = process_one_deletion_message(
                    body,
                    job_store,
                    segment_store,
                    storage,
                    reassembly_lock,
                    input_bucket,
                    output_bucket,
                )
                if ok:
                    receiver.delete(msg.receipt_handle)
            except Exception as e:
                job_id_ctx = "?"
                try:
                    raw = body.decode() if isinstance(body, bytes) else body
                    job_id_ctx = json.loads(raw).get("job_id", "?") or "?"
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
                logger.exception(
                    "deletion: job_id=%s failed to process message: %s", job_id_ctx, e
                )
        if not messages:
            time.sleep(poll_interval_sec)
