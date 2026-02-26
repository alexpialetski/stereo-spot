"""
Output-events consumer: S3 events (segment files and SageMaker async results).
Video-worker only releases inference_semaphore on SageMaker success/failure (backpressure).
SegmentCompletion, job status, and reassembly are handled by job-worker via job_status_events queue.
"""

from __future__ import annotations

import logging
import threading
import time

from stereo_spot_aws_adapters.dynamodb_stores import InferenceInvocationsStore
from stereo_spot_shared import parse_output_segment_key
from stereo_spot_shared.interfaces import QueueReceiver

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
    output_bucket: str,
    *,
    invocation_store: InferenceInvocationsStore | None = None,
    inference_semaphore: threading.Semaphore | None = None,
) -> bool:
    """
    Process a single output-events queue message (S3 event). Backpressure only.

    - jobs/ (segment files, final.mp4, .reassembly-done): ack only (job-worker handles status).
    - SageMaker success (sagemaker-async-responses/): release semaphore if set; do not delete
      from invocation store (job-worker deletes). Ack.
    - SageMaker failure (sagemaker-async-failures/): release semaphore if set; do not delete
      (job-worker handles). Ack.
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

    # jobs/*: ack only (job-worker consumes job_status_events and does SegmentCompletion/status)
    if key.startswith("jobs/"):
        result = parse_output_segment_key(bucket, key)
        if result is not None:
            logger.debug("output-events: segment file %s acknowledged", key)
        else:
            logger.debug("output-events: jobs key %s acknowledged", key)
        return True

    # SageMaker success: release semaphore only (job-worker writes SegmentCompletion and deletes)
    if key.startswith("sagemaker-async-responses/"):
        if invocation_store is not None:
            record = invocation_store.get(s3_uri)
            if record is not None:
                logger.debug(
                    "output-events: job_id=%s segment_index=%s SageMaker success, release",
                    record.get("job_id"),
                    record.get("segment_index"),
                )
        if inference_semaphore is not None:
            inference_semaphore.release()
        return True

    # SageMaker failure: release semaphore only (job-worker marks failed and deletes)
    if key.startswith("sagemaker-async-failures/"):
        if invocation_store is not None:
            record = invocation_store.get(s3_uri)
            if record is not None:
                logger.debug(
                    "output-events: job_id=%s segment_index=%s SageMaker failure, release",
                    record.get("job_id"),
                    record.get("segment_index"),
                )
        if inference_semaphore is not None:
            inference_semaphore.release()
        return True

    logger.debug("output-events: unknown prefix for key %s, delete", key)
    return True


def run_output_events_loop(
    receiver: QueueReceiver,
    output_bucket: str,
    *,
    invocation_store: InferenceInvocationsStore | None = None,
    inference_semaphore: threading.Semaphore | None = None,
    poll_interval_sec: float = 5.0,
) -> None:
    """Loop: output-events; release semaphore on SageMaker success/failure only; ack all."""
    logger.info("output-events loop started (backpressure only)")
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("output-events: received %s message(s)", len(messages))
        for msg in messages:
            try:
                process_one_output_event_message(
                    msg.body,
                    output_bucket,
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
