"""
Chunking loop: receive S3 event from queue, chunk source, upload segments, update job.
"""

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
        return False
    job_id = parse_input_key(payload.key)
    if job_id is None:
        return False
    job = job_store.get(job_id)
    if job is None:
        return False
    if job.status not in (JobStatus.CREATED, JobStatus.CHUNKING_IN_PROGRESS):
        # Already chunked or completed; idempotent skip
        return True
    mode = job.mode
    job_store.update(job_id, status=JobStatus.CHUNKING_IN_PROGRESS.value)
    try:
        source_bytes = storage.download(payload.bucket, payload.key)
    except Exception:
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
    while True:
        messages = receiver.receive(max_messages=1)
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
            except Exception:
                # Message will become visible again after visibility timeout
                pass
        if not messages:
            time.sleep(poll_interval_sec)
