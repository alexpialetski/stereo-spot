"""
Reassembly trigger: when all segments are complete for a chunking_complete job,
conditionally create ReassemblyTriggered and send job_id to reassembly queue.
"""

import logging

from stereo_spot_aws_adapters.dynamodb_stores import ReassemblyTriggeredLock
from stereo_spot_shared import JobStatus, ReassemblyPayload
from stereo_spot_shared.interfaces import (
    JobStore,
    QueueSender,
    SegmentCompletionStore,
)

logger = logging.getLogger(__name__)


def maybe_trigger_reassembly(
    job_id: str,
    job_store: JobStore,
    segment_store: SegmentCompletionStore,
    reassembly_triggered: ReassemblyTriggeredLock,
    reassembly_sender: QueueSender,
) -> None:
    """
    If job has status=chunking_complete and count(SegmentCompletions)==total_segments,
    conditionally create ReassemblyTriggered and send job_id to reassembly queue.
    """
    job = job_store.get(job_id)
    if job is None:
        return
    if job.status != JobStatus.CHUNKING_COMPLETE:
        logger.debug(
            "reassembly-trigger: job_id=%s skip (status=%s)",
            job_id,
            job.status.value,
        )
        return
    if job.total_segments is None or job.total_segments < 1:
        logger.warning(
            "reassembly-trigger: job_id=%s total_segments=%s",
            job_id,
            job.total_segments,
        )
        return
    count = len(segment_store.query_by_job(job_id))
    if count != job.total_segments:
        logger.debug(
            "reassembly-trigger: job_id=%s skip (completions=%s != total_segments=%s)",
            job_id,
            count,
            job.total_segments,
        )
        return
    if not reassembly_triggered.try_create_triggered(job_id):
        logger.info(
            "reassembly-trigger: job_id=%s already triggered (idempotent skip)",
            job_id,
        )
        return
    logger.info(
        "reassembly-trigger: job_id=%s sending to reassembly queue",
        job_id,
    )
    reassembly_sender.send(ReassemblyPayload(job_id=job_id).model_dump_json())
