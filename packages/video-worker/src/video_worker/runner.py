"""Video worker loop: receive S3 event, parse segment, run model, upload output, put completion."""

import time

from stereo_spot_shared import SegmentCompletion
from stereo_spot_shared.interfaces import ObjectStorage, QueueReceiver, SegmentCompletionStore

from .model_stub import process_segment
from .output_key import build_output_segment_key
from .s3_event import parse_s3_event_body


def _parse_s3_uri(s3_uri: str) -> tuple[str, str] | None:
    """Extract (bucket, key) from s3://bucket/key."""
    if not s3_uri.startswith("s3://"):
        return None
    rest = s3_uri[5:]
    if "/" not in rest:
        return None
    bucket, _, key = rest.partition("/")
    return bucket, key


def process_one_message(
    payload_str: str | bytes,
    storage: ObjectStorage,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
) -> bool:
    """
    Process a single video-worker queue message (S3 event body).

    Returns True if the message was processed successfully, False if skipped (invalid).
    """
    payload = parse_s3_event_body(payload_str)
    if payload is None:
        return False
    parsed = _parse_s3_uri(payload.segment_s3_uri)
    if parsed is None:
        return False
    input_bucket, input_key = parsed
    segment_bytes = storage.download(input_bucket, input_key)
    output_bytes = process_segment(segment_bytes)
    output_key = build_output_segment_key(payload.job_id, payload.segment_index)
    storage.upload(output_bucket, output_key, output_bytes)
    output_s3_uri = f"s3://{output_bucket}/{output_key}"
    completed_at = int(time.time())
    completion = SegmentCompletion(
        job_id=payload.job_id,
        segment_index=payload.segment_index,
        output_s3_uri=output_s3_uri,
        completed_at=completed_at,
        total_segments=payload.total_segments,
    )
    segment_store.put(completion)
    return True


def run_loop(
    receiver: QueueReceiver,
    storage: ObjectStorage,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    *,
    poll_interval_sec: float = 5.0,
) -> None:
    """Long-running loop: receive messages, process each, delete on success."""
    while True:
        messages = receiver.receive(max_messages=1)
        for msg in messages:
            body = msg.body
            try:
                ok = process_one_message(
                    body,
                    storage,
                    segment_store,
                    output_bucket,
                )
                if ok:
                    receiver.delete(msg.receipt_handle)
            except Exception:
                pass
        if not messages:
            time.sleep(poll_interval_sec)
