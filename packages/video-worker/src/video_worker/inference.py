"""
Inference queue consumer: receive S3 event (segment), run model (SageMaker/HTTP/stub),
upload result or invoke async; write SegmentCompletion for stub/HTTP.
SageMaker: invoke async, put to invocation store, delete message (completion via output-events).
Backpressure: optional semaphore limits in-flight invocations; output-events releases on completion.
"""

from __future__ import annotations

import logging
import threading
import time

from stereo_spot_aws_adapters.dynamodb_stores import InferenceInvocationsStore
from stereo_spot_shared import JobStatus, SegmentCompletion, VideoWorkerPayload
from stereo_spot_shared.interfaces import (
    JobStore,
    ObjectStorage,
    QueueReceiver,
    SegmentCompletionStore,
)

from .config import get_settings
from .model_http import invoke_http_endpoint
from .model_sagemaker import invoke_sagemaker_async
from .model_stub import process_segment
from .output_key import build_output_segment_key, build_output_segment_uri
from .s3_event import parse_s3_event_body
from .s3_uri import parse_s3_uri

logger = logging.getLogger(__name__)


def _job_id_for_inference_body(body: str | bytes) -> str:
    """Extract job_id from inference-queue S3 event body for logging; '?' if not parseable."""
    payload = parse_s3_event_body(body)
    return payload.job_id if payload else "?"


def _log_job_id_from_inference_body(body: str | bytes, fmt: str) -> None:
    """Log message with job_id extracted from inference body (for correlation in CloudWatch)."""
    job_id = _job_id_for_inference_body(body)
    logger.warning(fmt, job_id)


def _mark_job_failed(
    job_store: JobStore | None,
    payload: VideoWorkerPayload | None,
) -> None:
    """Update job status to FAILED and log; no-op if store or payload missing."""
    if job_store is None or payload is None:
        return
    try:
        job_store.update(payload.job_id, status=JobStatus.FAILED.value)
        logger.info("video-worker: job_id=%s marked failed", payload.job_id)
    except Exception as e:
        logger.exception(
            "video-worker: job_id=%s failed to mark job failed: %s",
            payload.job_id,
            e,
        )


def _use_sagemaker_backend() -> bool:
    return get_settings().use_sagemaker_backend


def _use_http_backend() -> bool:
    return get_settings().use_http_backend


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
        _log_job_id_from_inference_body(
            payload_str, "video-worker: job_id=%s invalid S3 event body"
        )
        return False
    logger.info(
        "video-worker: job_id=%s segment_index=%s/%s start",
        payload.job_id,
        payload.segment_index,
        payload.total_segments,
    )
    output_s3_uri = build_output_segment_uri(
        output_bucket, payload.job_id, payload.segment_index
    )
    completed_at = int(time.time())

    if _use_sagemaker_backend():
        raise ValueError(
            "SageMaker backend uses event-driven completion; use run_loop with invocation_store."
        )
    if _use_http_backend():
        http_url = get_settings().inference_http_url
        if not http_url:
            raise ValueError("INFERENCE_BACKEND=http requires INFERENCE_HTTP_URL")
        invoke_http_endpoint(
            http_url,
            payload.segment_s3_uri,
            output_s3_uri,
            mode=payload.mode.value,
        )
    else:
        parsed = parse_s3_uri(payload.segment_s3_uri)
        if parsed is None:
            return False
        input_bucket, input_key = parsed
        segment_bytes = storage.download(input_bucket, input_key)
        output_bytes = process_segment(segment_bytes)
        output_key = build_output_segment_key(payload.job_id, payload.segment_index)
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


def _max_in_flight() -> int:
    """Max concurrent SageMaker async invocations (1–20)."""
    return get_settings().inference_max_in_flight


def run_loop(
    receiver: QueueReceiver,
    storage: ObjectStorage,
    segment_store: SegmentCompletionStore,
    output_bucket: str,
    job_store: JobStore | None = None,
    *,
    invocation_store: InferenceInvocationsStore | None = None,
    inference_semaphore: threading.Semaphore | None = None,
    poll_interval_sec: float = 5.0,
) -> None:
    """Long-running loop: receive messages, process each, delete on success.
    When backend=sagemaker: invoke async, put store, delete message (completion via output-events).
    inference_semaphore: when set, acquire before each SageMaker invoke; output-events releases on
    completion (backpressure). job_store: on processing raise, job is marked failed."""
    backend = get_settings().inference_backend
    logger.info("video-worker loop started (backend=%s)", backend)

    if _use_sagemaker_backend():
        if invocation_store is None:
            raise ValueError("INFERENCE_BACKEND=sagemaker requires invocation_store")
        _run_loop_sagemaker_fire_and_forget(
            receiver,
            output_bucket,
            job_store,
            invocation_store,
            inference_semaphore=inference_semaphore,
            poll_interval_sec=poll_interval_sec,
        )
        return

    # Stub / HTTP: single-message processing
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
                logger.exception(
                    "video-worker: job_id=%s failed to process message: %s",
                    job_id_ctx, e,
                )
                _mark_job_failed(job_store, payload)
        if not messages:
            time.sleep(poll_interval_sec)


def _run_loop_sagemaker_fire_and_forget(
    receiver: QueueReceiver,
    output_bucket: str,
    job_store: JobStore | None,
    invocation_store: InferenceInvocationsStore,
    *,
    inference_semaphore: threading.Semaphore | None = None,
    poll_interval_sec: float = 5.0,
) -> None:
    """SageMaker-only: invoke async, put store, delete. Completion via output-events queue.
    If inference_semaphore is set, acquire before invoke (backpressure); output-events releases."""
    import boto3

    s = get_settings()
    endpoint_name = s.sagemaker_endpoint_name
    if not endpoint_name:
        raise ValueError("INFERENCE_BACKEND=sagemaker requires SAGEMAKER_ENDPOINT_NAME")
    region_name = s.sagemaker_region or None
    max_in_flight = _max_in_flight()
    sagemaker_client = boto3.client("sagemaker-runtime", region_name=region_name)

    while True:
        want = max(1, max_in_flight)
        messages = receiver.receive(max_messages=min(want, 10))
        if not messages:
            time.sleep(poll_interval_sec)
            continue
        for msg in messages:
            body = msg.body
            payload = parse_s3_event_body(body)
            if payload is None:
                _log_job_id_from_inference_body(
                    body, "video-worker: job_id=%s invalid S3 event body"
                )
                continue
            if inference_semaphore is not None:
                inference_semaphore.acquire()
            logger.info(
                "video-worker: job_id=%s segment_index=%s/%s invoking SageMaker async",
                payload.job_id,
                payload.segment_index,
                payload.total_segments,
            )
            output_s3_uri = build_output_segment_uri(
                output_bucket, payload.job_id, payload.segment_index
            )
            try:
                output_location = invoke_sagemaker_async(
                    payload.segment_s3_uri,
                    output_s3_uri,
                    endpoint_name,
                    mode=payload.mode.value,
                    region_name=region_name,
                    client=sagemaker_client,
                )
            except Exception as e:
                if inference_semaphore is not None:
                    inference_semaphore.release()
                logger.exception(
                    "video-worker: job_id=%s segment_index=%s invoke_async failed: %s",
                    payload.job_id, payload.segment_index, e,
                )
                _mark_job_failed(job_store, payload)
                continue
            invocation_store.put(
                output_location,
                payload.job_id,
                payload.segment_index,
                payload.total_segments,
                output_s3_uri,
            )
            receiver.delete(msg.receipt_handle)
            logger.info(
                "video-worker: job_id=%s segment_index=%s/%s invoked (done via output-events)",
                payload.job_id, payload.segment_index, payload.total_segments,
            )
