"""Video worker loop: receive S3 event, parse segment, run model, upload output, put completion."""

import logging
import os
import time

from stereo_spot_shared import SegmentCompletion
from stereo_spot_shared.interfaces import ObjectStorage, QueueReceiver, SegmentCompletionStore

from .model_sagemaker import invoke_sagemaker_endpoint
from .model_stub import process_segment
from .output_key import build_output_segment_key
from .s3_event import parse_s3_event_body

logger = logging.getLogger(__name__)


def _parse_s3_uri(s3_uri: str) -> tuple[str, str] | None:
    """Extract (bucket, key) from s3://bucket/key."""
    if not s3_uri.startswith("s3://"):
        return None
    rest = s3_uri[5:]
    if "/" not in rest:
        return None
    bucket, _, key = rest.partition("/")
    return bucket, key


def _use_sagemaker_backend() -> bool:
    return os.environ.get("INFERENCE_BACKEND", "stub").lower() == "sagemaker"


def process_one_message(
    payload_str: str | bytes,
    storage: ObjectStorage,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
) -> bool:
    """
    Process a single video-worker queue message (S3 event body).

    Returns True if the message was processed successfully, False if skipped (invalid).

    When INFERENCE_BACKEND=sagemaker: passes segment_s3_uri and output_s3_uri to
    the SageMaker endpoint (which writes the result to S3); video-worker only
    writes SegmentCompletion. When INFERENCE_BACKEND=stub (default): downloads
    segment, runs stub, uploads result, writes SegmentCompletion.
    """
    payload = parse_s3_event_body(payload_str)
    if payload is None:
        logger.warning("video-worker: invalid S3 event body")
        return False
    logger.info(
        "video-worker: job_id=%s segment_index=%s/%s start",
        payload.job_id,
        payload.segment_index,
        payload.total_segments,
    )
    output_key = build_output_segment_key(payload.job_id, payload.segment_index)
    output_s3_uri = f"s3://{output_bucket}/{output_key}"
    completed_at = int(time.time())

    if _use_sagemaker_backend():
        endpoint_name = os.environ.get("SAGEMAKER_ENDPOINT_NAME")
        if not endpoint_name:
            raise ValueError("INFERENCE_BACKEND=sagemaker requires SAGEMAKER_ENDPOINT_NAME")
        region_name = os.environ.get("SAGEMAKER_REGION") or None
        invoke_sagemaker_endpoint(
            payload.segment_s3_uri,
            output_s3_uri,
            endpoint_name,
            region_name=region_name or None,
        )
    else:
        parsed = _parse_s3_uri(payload.segment_s3_uri)
        if parsed is None:
            return False
        input_bucket, input_key = parsed
        segment_bytes = storage.download(input_bucket, input_key)
        output_bytes = process_segment(segment_bytes)
        storage.upload(output_bucket, output_key, output_bytes)

    completion = SegmentCompletion(
        job_id=payload.job_id,
        segment_index=payload.segment_index,
        output_s3_uri=output_s3_uri,
        completed_at=completed_at,
        total_segments=payload.total_segments,
    )
    segment_store.put(completion)
    logger.info(
        "video-worker: job_id=%s segment_index=%s/%s complete -> %s",
        payload.job_id,
        payload.segment_index,
        payload.total_segments,
        output_s3_uri,
    )
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
    backend = os.environ.get("INFERENCE_BACKEND", "stub")
    logger.info("video-worker loop started (backend=%s)", backend)
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("video-worker: received %s message(s)", len(messages))
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
            except Exception as e:
                logger.exception("video-worker: failed to process message: %s", e)
        if not messages:
            time.sleep(poll_interval_sec)
