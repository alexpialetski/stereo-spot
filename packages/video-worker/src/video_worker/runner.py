"""Video worker loop: receive S3 event, parse segment, run model, upload output, put completion."""

import logging
import os
import time

from stereo_spot_shared import JobStatus, SegmentCompletion, parse_output_segment_key
from stereo_spot_shared.interfaces import (
    JobStore,
    ObjectStorage,
    QueueReceiver,
    SegmentCompletionStore,
)

from .model_http import invoke_http_endpoint
from .model_sagemaker import invoke_sagemaker_endpoint
from .model_stub import process_segment
from .output_key import build_output_segment_key
from .s3_event import parse_s3_event_body, parse_s3_event_bucket_key

logger = logging.getLogger(__name__)


def _job_id_for_inference_body(body: str | bytes) -> str:
    """Extract job_id from inference-queue S3 event body for logging; return '?' if not parseable."""
    payload = parse_s3_event_body(body)
    return payload.job_id if payload else "?"


def _job_id_segment_for_segment_output_body(body: str | bytes) -> tuple[str, str]:
    """Extract (job_id, segment_index) from segment-output S3 event body for logging; return ('?', '?') if not parseable."""
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


def _log_job_id_from_inference_body(body: str | bytes, fmt: str) -> None:
    """Log message with job_id extracted from inference body (for correlation in CloudWatch)."""
    job_id = _job_id_for_inference_body(body)
    logger.warning(fmt, job_id)


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


def _use_http_backend() -> bool:
    return os.environ.get("INFERENCE_BACKEND", "stub").lower() == "http"


def process_one_message(
    payload_str: str | bytes,
    storage: ObjectStorage,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    job_store: JobStore | None = None,
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
        _log_job_id_from_inference_body(payload_str, "video-worker: job_id=%s invalid S3 event body")
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
            mode=payload.mode.value,
            region_name=region_name or None,
        )
        # SegmentCompletion is written by the segment-output consumer when the file appears in S3
        logger.info(
            "video-worker: job_id=%s segment_index=%s/%s invoked (completion via segment-output queue)",
            payload.job_id,
            payload.segment_index,
            payload.total_segments,
        )
        return True
    elif _use_http_backend():
        http_url = os.environ.get("INFERENCE_HTTP_URL")
        if not http_url:
            raise ValueError("INFERENCE_BACKEND=http requires INFERENCE_HTTP_URL")
        invoke_http_endpoint(
            http_url,
            payload.segment_s3_uri,
            output_s3_uri,
            mode=payload.mode.value,
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
    job_store: JobStore | None = None,
    *,
    poll_interval_sec: float = 5.0,
) -> None:
    """Long-running loop: receive messages, process each, delete on success.
    When job_store is set and processing raises, the job is marked failed."""
    backend = os.environ.get("INFERENCE_BACKEND", "stub")
    logger.info("video-worker loop started (backend=%s)", backend)
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("video-worker: received %s message(s)", len(messages))
        for msg in messages:
            body = msg.body
            payload = parse_s3_event_body(body)
            try:
                ok = process_one_message(
                    body,
                    storage,
                    segment_store,
                    output_bucket,
                    job_store=job_store,
                )
                if ok:
                    receiver.delete(msg.receipt_handle)
            except Exception as e:
                job_id_ctx = payload.job_id if payload else _job_id_for_inference_body(body)
                logger.exception("video-worker: job_id=%s failed to process message: %s", job_id_ctx, e)
                if job_store and payload:
                    try:
                        job_store.update(payload.job_id, status=JobStatus.FAILED.value)
                        logger.info("video-worker: job_id=%s marked failed", payload.job_id)
                    except Exception as update_err:
                        logger.exception("video-worker: job_id=%s failed to mark job failed: %s", payload.job_id, update_err)
        if not messages:
            time.sleep(poll_interval_sec)


def process_one_segment_output_message(
    payload_str: str | bytes,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
) -> bool:
    """
    Process a single segment-output queue message (S3 event: output bucket object created).

    Parses the key with parse_output_segment_key; if not a segment (e.g. final.mp4),
    returns False (caller may delete message as idempotent skip). Otherwise writes
    SegmentCompletion and returns True.
    """
    parsed = parse_s3_event_bucket_key(payload_str)
    if parsed is None:
        job_id, seg = _job_id_segment_for_segment_output_body(payload_str)
        logger.warning("segment-output: job_id=%s segment_index=%s invalid S3 event body", job_id, seg)
        return False
    bucket, key = parsed
    result = parse_output_segment_key(bucket, key)
    if result is None:
        job_id_from_key = key.split("/")[1] if key.startswith("jobs/") and len(key.split("/")) >= 2 else "?"
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
    return True


def run_segment_output_loop(
    receiver: QueueReceiver,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    *,
    poll_interval_sec: float = 5.0,
) -> None:
    """Long-running loop: receive segment-output messages, put SegmentCompletion, delete on success."""
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
