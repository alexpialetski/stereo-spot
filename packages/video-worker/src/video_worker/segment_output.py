"""
Segment-output queue consumer: receive S3 events from output bucket (segment files),
write SegmentCompletion, optionally trigger reassembly when all segments done.
"""

import logging
import time

from stereo_spot_aws_adapters.dynamodb_stores import ReassemblyTriggeredLock
from stereo_spot_shared import SegmentCompletion, parse_output_segment_key
from stereo_spot_shared.interfaces import (
    JobStore,
    QueueReceiver,
    QueueSender,
    SegmentCompletionStore,
)

from .reassembly_trigger import maybe_trigger_reassembly
from .s3_event import parse_s3_event_bucket_key

logger = logging.getLogger(__name__)


def _job_id_segment_for_segment_output_body(body: str | bytes) -> tuple[str, str]:
    """Extract (job_id, segment_index) from segment-output S3 event; ('?','?') if not parseable."""
    parsed = parse_s3_event_bucket_key(body)
    if parsed is None:
        return ("?", "?")
    bucket, key = parsed
    result = parse_output_segment_key(bucket, key)
    if result is None:
        # e.g. jobs/job-abc/final.mp4 -> still have job_id from key path
        parts = key.split("/")
        if len(parts) >= 2 and parts[0] == "jobs":
            return (parts[1], "?")
        return ("?", "?")
    job_id, segment_index = result
    return (str(job_id), str(segment_index))


def process_one_segment_output_message(
    payload_str: str | bytes,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    *,
    job_store: JobStore | None = None,
    reassembly_triggered: ReassemblyTriggeredLock | None = None,
    reassembly_sender: QueueSender | None = None,
) -> bool:
    """
    Process a single segment-output queue message (S3 event: output bucket object created).

    Parses the key with parse_output_segment_key; if not a segment (e.g. final.mp4),
    returns False (caller may delete message as idempotent skip). Otherwise writes
    SegmentCompletion and returns True.
    When job_store, reassembly_triggered, and reassembly_sender are all provided,
    calls maybe_trigger_reassembly after the put (trigger-on-write).
    """
    parsed = parse_s3_event_bucket_key(payload_str)
    if parsed is None:
        job_id, seg = _job_id_segment_for_segment_output_body(payload_str)
        logger.warning(
            "segment-output: job_id=%s segment_index=%s invalid S3 event body",
            job_id, seg,
        )
        return False
    bucket, key = parsed
    result = parse_output_segment_key(bucket, key)
    if result is None:
        parts = key.split("/")
        job_id_from_key = parts[1] if key.startswith("jobs/") and len(parts) >= 2 else "?"
        logger.debug("segment-output: job_id=%s skip non-segment key %s", job_id_from_key, key)
        return False
    job_id, segment_index = result
    output_s3_uri = f"s3://{output_bucket}/{key}"
    completed_at = int(time.time())
    completion = SegmentCompletion(
        job_id=job_id,
        segment_index=segment_index,
        output_s3_uri=output_s3_uri,
        completed_at=completed_at,
        total_segments=None,
    )
    segment_store.put(completion)
    logger.info(
        "segment-output: job_id=%s segment_index=%s -> %s",
        job_id,
        segment_index,
        output_s3_uri,
    )
    if job_store is not None and reassembly_triggered is not None and reassembly_sender is not None:
        maybe_trigger_reassembly(
            job_id,
            job_store,
            segment_store,
            reassembly_triggered,
            reassembly_sender,
        )
    return True


def run_segment_output_loop(
    receiver: QueueReceiver,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    *,
    job_store: JobStore | None = None,
    reassembly_triggered: ReassemblyTriggeredLock | None = None,
    reassembly_sender: QueueSender | None = None,
    poll_interval_sec: float = 5.0,
) -> None:
    """Loop: receive segment-output messages, put SegmentCompletion, delete on success."""
    logger.info("segment-output loop started")
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("segment-output: received %s message(s)", len(messages))
        for msg in messages:
            try:
                ok = process_one_segment_output_message(
                    msg.body,
                    segment_store,
                    output_bucket,
                    job_store=job_store,
                    reassembly_triggered=reassembly_triggered,
                    reassembly_sender=reassembly_sender,
                )
                if ok:
                    receiver.delete(msg.receipt_handle)
                else:
                    # Invalid or non-segment key; delete to avoid reprocessing
                    receiver.delete(msg.receipt_handle)
            except Exception as e:
                job_id_ctx, seg_ctx = _job_id_segment_for_segment_output_body(msg.body)
                logger.exception(
                    "segment-output: job_id=%s segment_index=%s failed to process message: %s",
                    job_id_ctx,
                    seg_ctx,
                    e,
                )
        if not messages:
            time.sleep(poll_interval_sec)
