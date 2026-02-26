"""
Job-status-events consumer: S3 events (segment files, final.mp4, SageMaker async results).
Writes SegmentCompletion, updates job status (completed/failed/reassembling), triggers reassembly.
No semaphore (backpressure is handled by video-worker via output-events).
"""

from __future__ import annotations

import logging
import time

from stereo_spot_aws_adapters.dynamodb_stores import (
    InferenceInvocationsStore,
    ReassemblyTriggeredLock,
)
from stereo_spot_shared import JobStatus, SegmentCompletion, parse_output_segment_key
from stereo_spot_shared.interfaces import (
    JobStore,
    QueueReceiver,
    QueueSender,
    SegmentCompletionStore,
)
from video_worker.reassembly_trigger import maybe_trigger_reassembly
from video_worker.s3_event import parse_s3_event_bucket_key

logger = logging.getLogger(__name__)


def _job_id_segment_from_body(body: str | bytes) -> tuple[str, str]:
    """(job_id, segment_index) from S3 body for logging; ('?','?') if invalid."""
    parsed = parse_s3_event_bucket_key(body)
    if parsed is None:
        return ("?", "?")
    bucket, key = parsed
    result = parse_output_segment_key(bucket, key)
    if result is None:
        parts = key.split("/")
        if len(parts) >= 2 and parts[0] == "jobs":
            return (parts[1], "?")
        return ("?", "?")
    job_id, segment_index = result
    return (str(job_id), str(segment_index))


def process_one_job_status_event_message(
    payload_str: str | bytes,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    *,
    job_store: JobStore,
    reassembly_triggered: ReassemblyTriggeredLock,
    reassembly_sender: QueueSender,
    invocation_store: InferenceInvocationsStore | None = None,
) -> bool:
    """
    Process a single job-status-events queue message (S3 event).

    - jobs/.../final.mp4 or .reassembly-done: set job completed and completed_at.
    - jobs/.../segments/*.mp4 (stub/HTTP): write SegmentCompletion, maybe_trigger_reassembly.
    - sagemaker-async-responses/: lookup store, write SegmentCompletion, delete, trigger.
    - sagemaker-async-failures/: lookup store, mark job failed, delete from store.
    Returns True if the message should be deleted (always True for idempotent processing).
    """
    parsed = parse_s3_event_bucket_key(payload_str)
    if parsed is None:
        job_id, seg = _job_id_segment_from_body(payload_str)
        raw = (
            payload_str.decode("utf-8", errors="replace")
            if isinstance(payload_str, bytes)
            else payload_str
        )
        body_preview = raw[:500]
        logger.warning(
            "job-status-events: job_id=%s segment_index=%s invalid S3 event body (preview=%s)",
            job_id,
            seg,
            body_preview,
        )
        return True  # delete to avoid poison

    bucket, key = parsed
    s3_uri = f"s3://{bucket}/{key}"

    # Reassembly complete: final.mp4 or .reassembly-done sentinel
    if key.startswith("jobs/") and (
        key.endswith("/final.mp4") or key.endswith("/.reassembly-done")
    ):
        parts = key.split("/")
        if len(parts) >= 3 and parts[0] == "jobs" and parts[1]:
            job_id = parts[1]
            try:
                job_store.update(
                    job_id,
                    status=JobStatus.COMPLETED.value,
                    completed_at=int(time.time()),
                )
                logger.info(
                    "job-status-events: job_id=%s reassembly complete -> completed",
                    job_id,
                )
            except Exception as e:
                logger.exception(
                    "job-status-events: job_id=%s failed to set completed: %s",
                    job_id,
                    e,
                )
        return True

    # Segment file (jobs/.../segments/*.mp4): stub/HTTP path - write SegmentCompletion and trigger
    if key.startswith("jobs/"):
        result = parse_output_segment_key(bucket, key)
        if result is not None:
            job_id, segment_index = result
            job = job_store.get(job_id)
            if job is not None and job.total_segments is not None:
                output_s3_uri = s3_uri
                completed_at = int(time.time())
                completion = SegmentCompletion(
                    job_id=job_id,
                    segment_index=segment_index,
                    output_s3_uri=output_s3_uri,
                    completed_at=completed_at,
                    total_segments=job.total_segments,
                )
                segment_store.put(completion)
                logger.info(
                    "job-status-events: job_id=%s segment_index=%s segment file -> completion",
                    job_id,
                    segment_index,
                )
                maybe_trigger_reassembly(
                    job_id,
                    job_store,
                    segment_store,
                    reassembly_triggered,
                    reassembly_sender,
                )
            else:
                logger.warning(
                    "job-status-events: job_id=%s job not found or no total_segments, skip",
                    job_id,
                )
        return True

    # SageMaker success: write SegmentCompletion, delete from store, trigger reassembly
    if key.startswith("sagemaker-async-responses/"):
        if invocation_store is None:
            logger.debug("job-status-events: no invocation store, skip SageMaker success %s", key)
            return True
        record = invocation_store.get(s3_uri)
        if record is None:
            logger.warning(
                "job-status-events: no invocation record for %s (idempotent delete)", s3_uri
            )
            return True
        job_id = record["job_id"]
        segment_index = record["segment_index"]
        total_segments = record["total_segments"]
        output_s3_uri = record["output_s3_uri"]
        completed_at = int(time.time())
        completion = SegmentCompletion(
            job_id=job_id,
            segment_index=segment_index,
            output_s3_uri=output_s3_uri,
            completed_at=completed_at,
            total_segments=total_segments,
        )
        segment_store.put(completion)
        invocation_store.delete(s3_uri)
        logger.info(
            "job-status-events: job_id=%s segment_index=%s SageMaker success -> %s",
            job_id,
            segment_index,
            output_s3_uri,
        )
        maybe_trigger_reassembly(
            job_id,
            job_store,
            segment_store,
            reassembly_triggered,
            reassembly_sender,
        )
        return True

    # SageMaker failure: mark job failed, delete from store
    if key.startswith("sagemaker-async-failures/"):
        if invocation_store is None:
            logger.debug("job-status-events: no invocation store, skip SageMaker failure %s", key)
            return True
        record = invocation_store.get(s3_uri)
        if record is not None:
            job_id = record["job_id"]
            segment_index = record["segment_index"]
            try:
                job_store.update(job_id, status=JobStatus.FAILED.value)
                logger.info(
                    "job-status-events: job_id=%s segment_index=%s SageMaker failure, job failed",
                    job_id,
                    segment_index,
                )
            except Exception as e:
                logger.exception(
                    "job-status-events: failed to mark job %s failed: %s", job_id, e
                )
            invocation_store.delete(s3_uri)
        else:
            logger.warning(
                "job-status-events: no invocation record for failure %s (idempotent delete)",
                s3_uri,
            )
        return True

    logger.debug("job-status-events: unknown prefix for key %s, delete", key)
    return True


def run_job_status_events_loop(
    receiver: QueueReceiver,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    *,
    job_store: JobStore,
    reassembly_triggered: ReassemblyTriggeredLock,
    reassembly_sender: QueueSender,
    invocation_store: InferenceInvocationsStore | None = None,
    poll_interval_sec: float = 5.0,
) -> None:
    """Loop: receive from job_status_events, process, delete."""
    logger.info("job-status-events loop started")
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("job-status-events: received %s message(s)", len(messages))
        for msg in messages:
            try:
                process_one_job_status_event_message(
                    msg.body,
                    segment_store,
                    output_bucket,
                    job_store=job_store,
                    reassembly_triggered=reassembly_triggered,
                    reassembly_sender=reassembly_sender,
                    invocation_store=invocation_store,
                )
                receiver.delete(msg.receipt_handle)
            except Exception as e:
                job_id_ctx, seg_ctx = _job_id_segment_from_body(msg.body)
                logger.exception(
                    "job-status-events: job_id=%s segment_index=%s failed to process message: %s",
                    job_id_ctx,
                    seg_ctx,
                    e,
                )
        if not messages:
            time.sleep(poll_interval_sec)
