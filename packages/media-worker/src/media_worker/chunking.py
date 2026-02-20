"""
Chunking loop: receive S3 event from queue, chunk source, upload segments, update job.
"""

import json
import logging
import os
import tempfile
import time

from stereo_spot_shared import (
    JobStatus,
    build_segment_key,
    parse_input_key,
)
from stereo_spot_shared.interfaces import JobStore, ObjectStorage, QueueReceiver

from .ffmpeg_chunk import DEFAULT_SEGMENT_DURATION_SEC, chunk_video_to_temp
from .s3_event import parse_s3_event_body

logger = logging.getLogger(__name__)


def _job_id_from_chunking_body(body: str | bytes) -> str:
    """Extract job_id from chunking-queue S3 event body for logging; return '?' if not parseable."""
    try:
        raw = body.decode() if isinstance(body, bytes) else body
        data = json.loads(raw)
        records = data.get("Records") or []
        first = records[0] if records else {}
        s3 = first.get("s3") or {}
        obj = s3.get("object") or {}
        key = obj.get("key") or ""
        if isinstance(key, str):
            from urllib.parse import unquote_plus
            key = unquote_plus(key)
            job_id = parse_input_key(key)
            return job_id or "?"
    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        pass
    return "?"


def process_one_chunking_message(
    payload_str: str | bytes,
    job_store: JobStore,
    storage: ObjectStorage,
    input_bucket: str,
    *,
    segment_duration_sec: int = DEFAULT_SEGMENT_DURATION_SEC,
) -> bool:
    """
    Process a single chunking queue message (S3 event body).

    Returns True if the message was processed successfully (job chunked and updated),
    False if the message should be skipped (invalid or job not found).
    """
    payload = parse_s3_event_body(payload_str)
    if payload is None:
        job_id_ctx = _job_id_from_chunking_body(payload_str)
        logger.warning("chunking: job_id=%s invalid S3 event body", job_id_ctx)
        return False
    job_id = parse_input_key(payload.key)
    if job_id is None:
        logger.warning("chunking: could not parse job_id from key=%s", getattr(payload, "key", ""))
        return False
    job = job_store.get(job_id)
    if job is None:
        logger.warning("chunking: job_id=%s not found", job_id)
        return False
    if job.status not in (JobStatus.CREATED, JobStatus.CHUNKING_IN_PROGRESS):
        logger.info("chunking: job_id=%s skip (status=%s)", job_id, job.status.value)
        return True
    logger.info("chunking: job_id=%s start (key=%s)", job_id, payload.key)
    mode = job.mode
    job_store.update(job_id, status=JobStatus.CHUNKING_IN_PROGRESS.value)
    try:
        source_bytes = storage.download(payload.bucket, payload.key)
    except Exception as e:
        logger.warning(
            "chunking: job_id=%s download failed (key=%s): %s",
            job_id, payload.key, e,
        )
        job_store.update(job_id, status=JobStatus.CREATED.value)
        raise
    with tempfile.NamedTemporaryFile(
        suffix=".mp4", delete=False
    ) as tmp_source:
        tmp_source.write(source_bytes)
        source_path = tmp_source.name
    try:
        segments, tmp = chunk_video_to_temp(
            source_path,
            segment_duration_sec=segment_duration_sec,
        )
        try:
            total = len(segments)
            for i, seg_path in enumerate(segments):
                key = build_segment_key(job_id, i, total, mode)
                with open(seg_path, "rb") as f:
                    storage.upload(input_bucket, key, f.read())
            job_store.update(
                job_id,
                status=JobStatus.CHUNKING_COMPLETE.value,
                total_segments=total,
            )
            logger.info("chunking: job_id=%s complete total_segments=%s", job_id, total)
        finally:
            tmp.cleanup()
    finally:
        try:
            os.unlink(source_path)
        except FileNotFoundError:
            pass
    return True


def run_chunking_loop(
    receiver: QueueReceiver,
    job_store: JobStore,
    storage: ObjectStorage,
    input_bucket: str,
    *,
    poll_interval_sec: float = 5.0,
    segment_duration_sec: int = DEFAULT_SEGMENT_DURATION_SEC,
) -> None:
    """
    Long-running loop: receive messages from chunking queue, process each, delete on success.
    """
    logger.info("chunking loop started")
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("chunking: received %s message(s)", len(messages))
        for msg in messages:
            body = msg.body
            try:
                ok = process_one_chunking_message(
                    body,
                    job_store,
                    storage,
                    input_bucket,
                    segment_duration_sec=segment_duration_sec,
                )
                if ok:
                    receiver.delete(msg.receipt_handle)
            except Exception as e:
                job_id_ctx = _job_id_from_chunking_body(body)
                logger.exception("chunking: job_id=%s failed to process message: %s", job_id_ctx, e)
                # Message will become visible again after visibility timeout
        if not messages:
            time.sleep(poll_interval_sec)
