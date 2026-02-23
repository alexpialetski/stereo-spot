"""
Job-events consumer: long-polls job-events SQS (EventBridge Pipes), normalizes (aws-adapters),
computes progress, pushes to SSE and sends Web Push on completed/failed.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from stereo_spot_shared import Job, JobEvent, JobTableChange, SegmentCompletionInsert

from .utils import compute_progress

if TYPE_CHECKING:
    from stereo_spot_shared.interfaces import QueueReceiver

logger = logging.getLogger(__name__)

# Registry: job_id -> list of asyncio.Queue; payloads are dicts (progress_percent, stage_label, ...)
SSERegistry = dict[str, list[asyncio.Queue[dict[str, Any]]]]


def _send_web_push_sync(
    subscriptions: list[dict],
    job_event: JobEvent,
    vapid_private_key: str,
    base_url: str,
) -> None:
    """Send Web Push to all subscriptions (run in executor; pywebpush is sync)."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not available; skipping Web Push")
        return
    title = "Job failed" if job_event.status == "failed" else "Job completed"
    body = job_event.title or job_event.job_id
    url = f"{base_url.rstrip('/')}/jobs/{job_event.job_id}"
    payload = json.dumps({"title": title, "body": body, "url": url})
    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": "mailto:noreply@stereo-spot.local"},
            )
        except WebPushException as e:
            logger.debug("Web Push failed for one subscription: %s", e)


class _SSEAndPushSink:
    """In-process JobEventsSink: push to SSE registry and send Web Push on completed/failed."""

    def __init__(
        self,
        registry: SSERegistry,
        push_subscriptions_store: Any,
        vapid_private_key: str | None,
        base_url: str,
    ) -> None:
        self._registry = registry
        self._push_store = push_subscriptions_store
        self._vapid_private_key = vapid_private_key
        self._base_url = base_url

    def send(self, job_event: JobEvent) -> None:
        payload = {
            "progress_percent": job_event.progress_percent,
            "stage_label": job_event.stage_label,
        }
        queues = self._registry.get(job_event.job_id)
        if queues:
            for q in list(queues):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
        if (
            job_event.status in ("completed", "failed")
            and self._push_store
            and self._vapid_private_key
        ):
            subs = self._push_store.list_all()
            if subs:
                _send_web_push_sync(
                    subs,
                    job_event,
                    self._vapid_private_key,
                    self._base_url,
                )


def _records_from_body(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract stream records from body: single record or { \"Records\": [ ... ] }."""
    if "Records" in data and isinstance(data["Records"], list):
        return data["Records"]
    # Single record (object with eventSourceARN, dynamodb, etc.)
    if "eventSourceARN" in data or "dynamodb" in data:
        return [data]
    return []


def _handle_normalized(
    normalized: JobTableChange | SegmentCompletionInsert,
    job_store: Any,
    segment_store: Any,
    sink: _SSEAndPushSink,
) -> None:
    """Compute progress from normalized event and send JobEvent via sink (bridge handle logic)."""
    if isinstance(normalized, JobTableChange):
        job = Job.model_validate(normalized.new_image)
        progress_percent, stage_label = compute_progress(job, segment_store)
        job_event = JobEvent(
            job_id=job.job_id,
            status=job.status.value,
            progress_percent=progress_percent,
            stage_label=stage_label,
            title=job.title,
            completed_at=job.completed_at,
        )
        sink.send(job_event)
        return
    if isinstance(normalized, SegmentCompletionInsert):
        job = job_store.get(normalized.job_id, consistent_read=True)
        if job is None:
            return
        progress_percent, stage_label = compute_progress(job, segment_store)
        job_event = JobEvent(
            job_id=normalized.job_id,
            status=job.status.value,
            progress_percent=progress_percent,
            stage_label=stage_label,
            title=job.title,
            completed_at=job.completed_at,
        )
        sink.send(job_event)
        return


async def run_job_events_consumer(
    receiver: "QueueReceiver",
    registry: SSERegistry,
    job_store: Any,
    segment_store: Any,
    normalizer: Callable[[dict[str, Any]], Any],
    *,
    push_subscriptions_store: Any = None,
    vapid_private_key: str | None = None,
    base_url: str = "http://localhost:8000",
) -> None:
    """
    Long-poll job-events queue; parse records, normalize, handle, push to SSE + Web Push.
    Runs until cancelled.
    """
    sink = _SSEAndPushSink(
        registry,
        push_subscriptions_store or _NoPushStore(),
        vapid_private_key,
        base_url,
    )
    while True:
        try:
            messages = await asyncio.to_thread(receiver.receive, 10)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("job-events receive failed: %s", e)
            await asyncio.sleep(5)
            continue
        for msg in messages:
            try:
                body = msg.body
                if isinstance(body, bytes):
                    body = body.decode("utf-8")
                data = json.loads(body)
                records = _records_from_body(data)
                for record in records:
                    normalized = normalizer(record)
                    if normalized is not None:
                        _handle_normalized(normalized, job_store, segment_store, sink)
                await asyncio.to_thread(receiver.delete, msg.receipt_handle)
            except Exception as e:
                logger.exception("job-events message handling failed: %s", e)


class _NoPushStore:
    """Placeholder when push_subscriptions_store is None."""

    def list_all(self) -> list:
        return []