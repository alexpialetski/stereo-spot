"""
Reassembly loop: receive job_id, acquire lock, concat segments, upload final, update Job.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Protocol

from stereo_spot_shared import JobStatus, ReassemblyPayload
from stereo_spot_shared.interfaces import (
    JobStore,
    ObjectStorage,
    QueueReceiver,
    SegmentCompletionStore,
)

from .concat import build_concat_list_paths, concat_segments_to_file
from .output_key import build_final_key

logger = logging.getLogger(__name__)


class ReassemblyLock(Protocol):
    """Protocol for reassembly single-run lock (e.g. ReassemblyTriggered table)."""

    def try_acquire(self, job_id: str) -> bool:
        """Return True if this worker acquired the lock, False otherwise."""
        ...


def _parse_reassembly_body(body: str | bytes) -> ReassemblyPayload | None:
    """Parse queue message body as ReassemblyPayload (JSON with job_id)."""
    try:
        raw = body.decode() if isinstance(body, bytes) else body
        data = json.loads(raw)
        return ReassemblyPayload.model_validate(data)
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def process_one_reassembly_message(
    payload_str: str | bytes,
    job_store: JobStore,
    segment_store: SegmentCompletionStore,
    storage: ObjectStorage,
    reassembly_lock: ReassemblyLock,
    output_bucket: str,
) -> bool:
    """
    Process a single reassembly queue message (job_id).

    Returns True if the message was processed (concat run or skipped idempotently),
    False if the message should be skipped (invalid or lock not acquired).
    """
    payload = _parse_reassembly_body(payload_str)
    if payload is None:
        logger.warning("reassembly: job_id=? invalid message body")
        return False
    job_id = payload.job_id
    logger.info("reassembly: job_id=%s received", job_id)

    if not reassembly_lock.try_acquire(job_id):
        logger.info("reassembly: job_id=%s lock not acquired (another worker)", job_id)
        return True

    job = job_store.get(job_id)
    if job is None:
        logger.warning("reassembly: job_id=%s job not found", job_id)
        return False
    if job.status == JobStatus.COMPLETED:
        logger.info("reassembly: job_id=%s already completed", job_id)
        return True

    final_key = build_final_key(job_id)
    if storage.exists(output_bucket, final_key):
        logger.info("reassembly: job_id=%s final.mp4 already exists (idempotent)", job_id)
        job_store.update(
            job_id,
            status=JobStatus.COMPLETED.value,
            completed_at=int(time.time()),
        )
        return True

    completions = segment_store.query_by_job(job_id)
    if not completions:
        logger.warning("reassembly: job_id=%s no segment completions", job_id)
        return False
    if job.total_segments is not None and len(completions) != job.total_segments:
        logger.warning(
            "reassembly: job_id=%s completions=%s != total_segments=%s",
            job_id,
            len(completions),
            job.total_segments,
        )
        return False
    logger.info("reassembly: job_id=%s concat %s segments -> final.mp4", job_id, len(completions))

    with tempfile.TemporaryDirectory(prefix="reassembly_") as tmpdir:
        segment_dir = Path(tmpdir)
        segment_paths = build_concat_list_paths(
            completions, storage, output_bucket, segment_dir
        )
        final_local = segment_dir / "final.mp4"
        concat_segments_to_file(segment_paths, final_local)
        storage.upload_file(output_bucket, final_key, str(final_local))

    job_store.update(
        job_id,
        status=JobStatus.COMPLETED.value,
        completed_at=int(time.time()),
    )
    logger.info("reassembly: job_id=%s completed", job_id)
    return True


def run_reassembly_loop(
    receiver: QueueReceiver,
    job_store: JobStore,
    segment_store: SegmentCompletionStore,
    storage: ObjectStorage,
    reassembly_lock: ReassemblyLock,
    output_bucket: str,
    *,
    poll_interval_sec: float = 5.0,
) -> None:
    """
    Long-running loop: receive messages from reassembly queue, process each, delete on success.
    If lock is not acquired, delete message (another worker will not process it either).
    """
    logger.info("reassembly loop started")
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("reassembly: received %s message(s)", len(messages))
        for msg in messages:
            body = msg.body
            try:
                ok = process_one_reassembly_message(
                    body,
                    job_store,
                    segment_store,
                    storage,
                    reassembly_lock,
                    output_bucket,
                )
                if ok:
                    receiver.delete(msg.receipt_handle)
            except Exception as e:
                job_id_ctx = "?"
                try:
                    raw = body.decode() if isinstance(body, bytes) else body
                    job_id_ctx = json.loads(raw).get("job_id", "?") or "?"
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
                logger.exception("reassembly: job_id=%s failed to process message: %s", job_id_ctx, e)
                # Message returns to queue after visibility timeout for retry
        if not messages:
            time.sleep(poll_interval_sec)
