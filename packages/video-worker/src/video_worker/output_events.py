"""
Output-events consumer: S3 events (segment files and SageMaker async results).
Segment file: ack only. SageMaker success: write SegmentCompletion and trigger reassembly.
When inference_semaphore is set, release on SageMaker success/failure to free a slot (backpressure).
"""

from __future__ import annotations

import logging
import threading
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

from .reassembly_trigger import maybe_trigger_reassembly
from .s3_event import parse_s3_event_bucket_key

logger = logging.getLogger(__name__)


def _job_id_segment_from_body(body: str | bytes) -> tuple[str, str]:
    """(job_id, segment_index) from output-event S3 body for logging; ('?','?') if invalid."""
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


def process_one_output_event_message(
    payload_str: str | bytes,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    *,
    job_store: JobStore | None = None,
    reassembly_triggered: ReassemblyTriggeredLock | None = None,
    reassembly_sender: QueueSender | None = None,
    invocation_store: InferenceInvocationsStore | None = None,
    inference_semaphore: threading.Semaphore | None = None,
) -> bool:
    """
    Process a single output-events queue message (S3 event: segment file or SageMaker async result).

    - jobs/.../final.mp4 or jobs/.../.reassembly-done: when job_store is provided, set job
      to completed and completed_at; then ack. (Media-worker writes these; video-worker
      owns job status for this phase.)
    - Segment file (jobs/.../segments/*.mp4): ack only; do not write SegmentCompletion.
    - SageMaker success (sagemaker-async-responses/): lookup store, write SegmentCompletion,
      trigger reassembly, delete from store.
    - SageMaker failure (sagemaker-async-failures/): lookup store, optionally mark failed, delete.
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
            "output-events: job_id=%s segment_index=%s invalid S3 event body (preview=%s)",
            job_id,
            seg,
            body_preview,
        )
        return True  # delete to avoid poison

    bucket, key = parsed
    s3_uri = f"s3://{bucket}/{key}"

    # Reassembly complete: final.mp4 or .reassembly-done sentinel → video-worker sets job completed
    if key.startswith("jobs/") and (
        key.endswith("/final.mp4") or key.endswith("/.reassembly-done")
    ):
        parts = key.split("/")
        if len(parts) >= 3 and parts[0] == "jobs" and parts[1]:
            job_id = parts[1]
            if job_store is not None:
                try:
                    job_store.update(
                        job_id,
                        status=JobStatus.COMPLETED.value,
                        completed_at=int(time.time()),
                    )
                    logger.info(
                        "output-events: job_id=%s reassembly complete -> completed",
                        job_id,
                    )
                except Exception as e:
                    # Best effort: log and ack to avoid poison; job may stay reassembling
                    logger.exception(
                        "output-events: job_id=%s failed to set completed: %s",
                        job_id,
                        e,
                    )
            else:
                logger.debug("output-events: no job_store, skip completed update for %s", key)
        return True

    # Segment file: acknowledge only (no SegmentCompletion)
    if key.startswith("jobs/"):
        result = parse_output_segment_key(bucket, key)
        if result is not None:
            logger.debug("output-events: segment file %s acknowledged (no completion)", key)
        else:
            logger.debug("output-events: non-segment key %s acknowledged", key)
        return True

    # SageMaker success: write SegmentCompletion and trigger reassembly
    if key.startswith("sagemaker-async-responses/"):
        if invocation_store is None:
            logger.debug("output-events: no invocation store, skip SageMaker success %s", key)
            return True
        record = invocation_store.get(s3_uri)
        if record is None:
            logger.warning("output-events: no invocation record for %s (idempotent delete)", s3_uri)
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
        if inference_semaphore is not None:
            inference_semaphore.release()
        logger.info(
            "output-events: job_id=%s segment_index=%s SageMaker success -> %s",
            job_id, segment_index, output_s3_uri,
        )
        if (
            job_store is not None
            and reassembly_triggered is not None
            and reassembly_sender is not None
        ):
            maybe_trigger_reassembly(
                job_id,
                job_store,
                segment_store,
                reassembly_triggered,
                reassembly_sender,
            )
        return True

    # SageMaker failure: optional mark job failed, delete from store
    if key.startswith("sagemaker-async-failures/"):
        if invocation_store is None:
            logger.debug("output-events: no invocation store, skip SageMaker failure %s", key)
            return True
        record = invocation_store.get(s3_uri)
        if record is not None:
            job_id = record["job_id"]
            segment_index = record["segment_index"]
            if job_store is not None:
                try:
                    job_store.update(job_id, status=JobStatus.FAILED.value)
                    logger.info(
                        "output-events: job_id=%s segment_index=%s SageMaker failure, job failed",
                        job_id, segment_index,
                    )
                except Exception as e:
                    logger.exception("output-events: failed to mark job %s failed: %s", job_id, e)
            invocation_store.delete(s3_uri)
            if inference_semaphore is not None:
                inference_semaphore.release()
        else:
            logger.warning(
                "output-events: no invocation record for failure %s (idempotent delete)",
                s3_uri,
            )
            # Release semaphore to avoid permanent leak: store is keyed by success URI,
            # so failure events never find a record; slot would otherwise stay held.
            if inference_semaphore is not None:
                inference_semaphore.release()
        return True

    # Unknown prefix: delete idempotently
    logger.debug("output-events: unknown prefix for key %s, delete", key)
    return True


def run_output_events_loop(
    receiver: QueueReceiver,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    *,
    job_store: JobStore | None = None,
    reassembly_triggered: ReassemblyTriggeredLock | None = None,
    reassembly_sender: QueueSender | None = None,
    invocation_store: InferenceInvocationsStore | None = None,
    inference_semaphore: threading.Semaphore | None = None,
    poll_interval_sec: float = 5.0,
) -> None:
    """Loop: output-events; segment=ack only, SM success=SegmentCompletion+reassembly; delete.
    inference_semaphore: when set, release on SageMaker success/failure (backpressure)."""
    logger.info("output-events loop started")
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("output-events: received %s message(s)", len(messages))
        for msg in messages:
            try:
                process_one_output_event_message(
                    msg.body,
                    segment_store,
                    output_bucket,
                    job_store=job_store,
                    reassembly_triggered=reassembly_triggered,
                    reassembly_sender=reassembly_sender,
                    invocation_store=invocation_store,
                    inference_semaphore=inference_semaphore,
                )
                receiver.delete(msg.receipt_handle)
            except Exception as e:
                job_id_ctx, seg_ctx = _job_id_segment_from_body(msg.body)
                logger.exception(
                    "output-events: job_id=%s segment_index=%s failed to process message: %s",
                    job_id_ctx,
                    seg_ctx,
                    e,
                )
        if not messages:
            time.sleep(poll_interval_sec)
