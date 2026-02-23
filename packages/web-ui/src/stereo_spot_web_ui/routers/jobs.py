"""Jobs and dashboard routes: list, create, detail, progress, play, delete."""

import asyncio
import base64
import json
import logging
import re
import time
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from stereo_spot_shared import (
    DeletionPayload,
    Job,
    JobStatus,
    JobStore,
    ObjectStorage,
    SegmentCompletionStore,
    StereoMode,
    YoutubeIngestPayload,
)
from stereo_spot_shared.interfaces import OperatorLinksProvider, QueueSender

from ..constants import (
    INPUT_KEY_TEMPLATE,
    OUTPUT_FINAL_KEY_TEMPLATE,
    PLAYBACK_PRESIGN_EXPIRY_SEC,
    PROGRESS_KEEPALIVE_SEC,
    PROGRESS_POLL_SEC,
    PROGRESS_STREAM_TIMEOUT_SEC,
)
from ..deps import (
    get_deletion_queue_sender,
    get_ingest_queue_sender_optional,
    get_input_bucket,
    get_job_store,
    get_object_storage,
    get_operator_links_provider,
    get_output_bucket,
    get_segment_completion_store,
    get_templates,
)
from ..utils import (
    compute_progress,
    get_eta_seconds_per_mb,
    normalize_title_for_storage,
    safe_download_filename,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class PatchJobRequest(BaseModel):
    """Request body for PATCH /jobs/{job_id} (set display title and timing from upload)."""

    title: str = Field(
        ..., min_length=1, max_length=500, description="Display name (e.g. upload filename)"
    )
    source_file_size_bytes: int | None = Field(
        None,
        ge=1,
        le=10 * 1024 * 1024 * 1024,
        description="Size of uploaded file in bytes (for ETA)",
    )


class IngestFromUrlRequest(BaseModel):
    """Request body for POST /jobs/{job_id}/ingest-from-url."""

    source_url: str = Field(..., min_length=1, description="Video URL (e.g. YouTube)")


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Dashboard: welcome and link to create job / list jobs."""
    return templates.TemplateResponse(request, "dashboard.html", {"request": request})


@router.get("/jobs", response_class=HTMLResponse)
async def list_jobs(
    request: Request,
    job_store: JobStore = Depends(get_job_store),
    templates: Jinja2Templates = Depends(get_templates),
    limit: int = 20,
    next_token: str | None = None,
) -> HTMLResponse:
    """Unified jobs page: in-progress (View link) + completed (Play link)."""
    in_progress = job_store.list_in_progress(limit=limit)
    exclusive_start_key = None
    if next_token:
        try:
            raw = base64.urlsafe_b64decode(next_token.encode())
            exclusive_start_key = json.loads(raw.decode())
        except Exception:
            exclusive_start_key = None
    completed_items, next_key = job_store.list_completed(
        limit=limit, exclusive_start_key=exclusive_start_key
    )
    next_token_out = None
    if next_key:
        next_token_out = base64.urlsafe_b64encode(
            json.dumps(next_key, default=str).encode()
        ).decode()
    removed = request.query_params.get("removed") == "1"
    return templates.TemplateResponse(
        request,
        "jobs_list.html",
        {
            "request": request,
            "in_progress_jobs": in_progress,
            "completed_jobs": completed_items,
            "next_token": next_token_out,
            "removed": removed,
        },
    )


@router.post("/jobs")
async def create_job(
    request: Request,
    mode: str = Form(..., description="anaglyph or sbs"),
    job_store: JobStore = Depends(get_job_store),
    object_storage: ObjectStorage = Depends(get_object_storage),
    input_bucket: str = Depends(get_input_bucket),
) -> RedirectResponse:
    """Create job (put Job status=created), presigned PUT for input key, redirect to job page."""
    job_id = str(uuid.uuid4())
    stereo_mode = StereoMode(mode)
    now = int(time.time())
    job = Job(
        job_id=job_id,
        mode=stereo_mode,
        status=JobStatus.CREATED,
        created_at=now,
    )
    job_store.put(job)
    logger.info("job_id=%s created mode=%s", job_id, mode)
    return RedirectResponse(url=request.url_for("job_detail", job_id=job_id), status_code=303)


# YouTube URL patterns: youtube.com/watch?v=ID or youtu.be/ID (optional query string)
YOUTUBE_URL_RE = re.compile(
    r"^https?://"
    r"(?:www\.)?"
    r"(?:youtube\.com/watch\?v=[\w-]+(?:&[^\s]*)?|youtu\.be/[\w-]+(?:\?[^\s]*)?)"
    r"$",
    re.IGNORECASE,
)


def _is_youtube_url(s: str) -> bool:
    """Return True if s looks like a supported YouTube URL."""
    s = (s or "").strip()
    return bool(YOUTUBE_URL_RE.match(s))


@router.post("/jobs/from-url")
async def create_job_from_url(
    request: Request,
    mode: str = Form(..., description="anaglyph or sbs"),
    source_url: str = Form(..., description="Video URL (e.g. YouTube)"),
    source_type: str = Form("youtube", description="Source type (e.g. youtube)"),
    job_store: JobStore = Depends(get_job_store),
    ingest_sender: QueueSender | None = Depends(get_ingest_queue_sender_optional),
) -> RedirectResponse:
    """Create job and send URL to ingest queue; redirect to job page."""
    if ingest_sender is None:
        raise HTTPException(
            status_code=503,
            detail="YouTube URL ingest is not enabled for this deployment.",
        )
    source_url = source_url.strip()
    if not _is_youtube_url(source_url):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported (e.g. youtube.com/watch?v=… or youtu.be/…).",
        )
    job_id = str(uuid.uuid4())
    stereo_mode = StereoMode(mode)
    now = int(time.time())
    job = Job(
        job_id=job_id,
        mode=stereo_mode,
        status=JobStatus.CREATED,
        created_at=now,
    )
    job_store.put(job)
    # Use YouTube payload for youtube (and yt-dlp–compatible) URLs; add other variants when needed.
    payload = YoutubeIngestPayload(
        job_id=job_id,
        source_url=source_url,
    )
    ingest_sender.send(payload.model_dump_json())
    logger.info("job_id=%s created from URL mode=%s", job_id, mode)
    return RedirectResponse(url=request.url_for("job_detail", job_id=job_id), status_code=303)


@router.patch("/jobs/{job_id}", status_code=204)
async def patch_job(
    job_id: str,
    body: PatchJobRequest,
    job_store: JobStore = Depends(get_job_store),
) -> None:
    """Set job display title and timing (from upload). Called after successful upload."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == JobStatus.DELETED:
        raise HTTPException(status_code=404, detail="Job not found")
    normalized = normalize_title_for_storage(body.title)
    update_kw: dict = {"title": normalized}
    if job.uploaded_at is None:
        update_kw["uploaded_at"] = int(time.time())
    if body.source_file_size_bytes is not None:
        update_kw["source_file_size_bytes"] = body.source_file_size_bytes
    job_store.update(job_id, **update_kw)
    logger.info(
        "job_id=%s title=%s uploaded_at/size set=%s",
        job_id,
        normalized,
        body.source_file_size_bytes is not None,
    )


@router.post("/jobs/{job_id}/ingest-from-url", status_code=204)
async def ingest_job_from_url(
    job_id: str,
    body: IngestFromUrlRequest,
    job_store: JobStore = Depends(get_job_store),
    ingest_sender: QueueSender | None = Depends(get_ingest_queue_sender_optional),
) -> None:
    """Send URL to ingest queue for an existing job in CREATED status."""
    if ingest_sender is None:
        raise HTTPException(
            status_code=503,
            detail="YouTube URL ingest is not enabled for this deployment.",
        )
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == JobStatus.DELETED:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.CREATED:
        raise HTTPException(
            status_code=400,
            detail="Job already has source; only jobs waiting for upload can ingest from URL.",
        )
    source_url = body.source_url.strip()
    if not _is_youtube_url(source_url):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported (e.g. youtube.com/watch?v=… or youtu.be/…).",
        )
    payload = YoutubeIngestPayload(job_id=job_id, source_url=source_url)
    ingest_sender.send(payload.model_dump_json())
    logger.info("job_id=%s ingest-from-url queued", job_id)


@router.get("/jobs/{job_id}/events")
async def job_progress_events(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
    segment_store: SegmentCompletionStore = Depends(get_segment_completion_store),
):
    """
    Server-Sent Events stream: progress_percent and stage_label.
    Polls job + segment completions every few seconds; closes when completed or timeout.
    """
    async def generate() -> str:
        logger.debug("job_id=%s events stream started", job_id)
        start = time.monotonic()
        last_keepalive = start
        last_percent = -1
        last_label = ""
        try:
            while (time.monotonic() - start) < PROGRESS_STREAM_TIMEOUT_SEC:
                job = job_store.get(job_id, consistent_read=True)
                if job is None:
                    logger.warning("job_id=%s events stream: job not found", job_id)
                    payload = {"progress_percent": 0, "stage_label": "Not found"}
                    yield f"data: {json.dumps(payload)}\n\n"
                    return
                percent, label = compute_progress(job, segment_store)
                if percent != last_percent or label != last_label:
                    last_percent = percent
                    last_label = label
                    payload = {"progress_percent": percent, "stage_label": label}
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_keepalive = time.monotonic()
                elif time.monotonic() - last_keepalive >= PROGRESS_KEEPALIVE_SEC:
                    yield ": keepalive\n\n"
                    last_keepalive = time.monotonic()
                if job.status == JobStatus.COMPLETED:
                    if last_percent != 100 or last_label != "Completed":
                        payload = {"progress_percent": 100, "stage_label": "Completed"}
                        yield f"data: {json.dumps(payload)}\n\n"
                    logger.debug("job_id=%s events stream ended (completed)", job_id)
                    return
                await asyncio.sleep(PROGRESS_POLL_SEC)
            logger.debug("job_id=%s events stream ended (timeout)", job_id)
        except asyncio.CancelledError:
            logger.debug("job_id=%s events stream ended (client disconnect)", job_id)
            raise

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
    object_storage: ObjectStorage = Depends(get_object_storage),
    segment_store: SegmentCompletionStore = Depends(get_segment_completion_store),
    input_bucket: str = Depends(get_input_bucket),
    output_bucket: str = Depends(get_output_bucket),
    operator_links: OperatorLinksProvider | None = Depends(get_operator_links_provider),
    templates: Jinja2Templates = Depends(get_templates),
    ingest_sender: QueueSender | None = Depends(get_ingest_queue_sender_optional),
) -> HTMLResponse:
    """Job detail: upload URL + instructions if status=created; otherwise status + progress."""
    job = job_store.get(job_id)
    if job is None:
        logger.warning("job_id=%s not found (detail)", job_id)
        return HTMLResponse(content="Job not found", status_code=404)
    if job.status == JobStatus.DELETED:
        logger.info("job_id=%s detail requested but job is deleted", job_id)
        return HTMLResponse(content="Job not found", status_code=404)
    logger.info("job_id=%s detail status=%s", job_id, job.status.value)
    upload_url = None
    playback_url = None
    download_url = None
    if job.status == JobStatus.CREATED:
        input_key = INPUT_KEY_TEMPLATE.format(job_id=job_id)
        upload_url = object_storage.presign_upload(
            input_bucket, input_key, expires_in=3600
        )
    # When INGESTING, do not show upload block (worker is fetching from URL)
    if job.status == JobStatus.COMPLETED:
        key = OUTPUT_FINAL_KEY_TEMPLATE.format(job_id=job_id)
        playback_url = object_storage.presign_download(
            output_bucket, key, expires_in=PLAYBACK_PRESIGN_EXPIRY_SEC
        )
        download_filename = safe_download_filename(job.title)
        download_url = object_storage.presign_download(
            output_bucket,
            key,
            expires_in=PLAYBACK_PRESIGN_EXPIRY_SEC,
            response_content_disposition=f'attachment; filename="{download_filename}"',
        )
    progress_percent, stage_label = compute_progress(job, segment_store)
    eta_seconds_per_mb = get_eta_seconds_per_mb(job_store, request.app)
    show_eta = eta_seconds_per_mb > 0
    conversion_duration_sec = None
    conversion_sec_per_mb = None
    if (
        job.status == JobStatus.COMPLETED
        and job.uploaded_at is not None
        and job.completed_at is not None
        and job.source_file_size_bytes is not None
        and job.source_file_size_bytes > 0
    ):
        conversion_duration_sec = job.completed_at - job.uploaded_at
        if conversion_duration_sec > 0:
            conversion_sec_per_mb = conversion_duration_sec / (
                job.source_file_size_bytes / 1e6
            )
    cloudwatch_logs_url = (
        operator_links.get_job_logs_url(job.job_id) if operator_links else None
    )
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "request": request,
            "job": job,
            "upload_url": upload_url,
            "ingest_from_url_available": ingest_sender is not None,
            "playback_url": playback_url,
            "download_url": download_url,
            "progress_percent": progress_percent,
            "stage_label": stage_label,
            "eta_seconds_per_mb": eta_seconds_per_mb,
            "show_eta": show_eta,
            "conversion_duration_sec": conversion_duration_sec,
            "conversion_sec_per_mb": conversion_sec_per_mb,
            "cloudwatch_logs_url": cloudwatch_logs_url,
        },
    )


@router.get("/jobs/{job_id}/play", response_model=None)
async def play(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
    object_storage: ObjectStorage = Depends(get_object_storage),
    output_bucket: str = Depends(get_output_bucket),
) -> RedirectResponse | HTMLResponse:
    """Redirect to presigned GET URL for jobs/{job_id}/final.mp4."""
    job = job_store.get(job_id)
    if job is None:
        logger.warning("job_id=%s not found (play)", job_id)
        return HTMLResponse(content="Job not found", status_code=404)
    if job.status != JobStatus.COMPLETED:
        logger.info("job_id=%s play skipped status=%s", job_id, job.status.value)
        return HTMLResponse(
            content="Job not completed yet.",
            status_code=400,
        )
    logger.info("job_id=%s play redirect to final.mp4", job_id)
    key = OUTPUT_FINAL_KEY_TEMPLATE.format(job_id=job_id)
    playback_url = object_storage.presign_download(
        output_bucket, key, expires_in=PLAYBACK_PRESIGN_EXPIRY_SEC
    )
    return RedirectResponse(url=playback_url, status_code=302)


@router.post("/jobs/{job_id}/delete", response_model=None)
async def delete_job(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
    deletion_sender: QueueSender = Depends(get_deletion_queue_sender),
) -> RedirectResponse | HTMLResponse:
    """Soft-delete job (status=deleted) and enqueue cleanup.
    Only allowed for completed or failed jobs."""
    job = job_store.get(job_id)
    if job is None:
        logger.warning("job_id=%s not found (delete)", job_id)
        return HTMLResponse(content="Job not found", status_code=404)
    if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
        logger.info("job_id=%s delete rejected status=%s", job_id, job.status.value)
        return HTMLResponse(
            content="Can only remove completed or failed jobs.",
            status_code=400,
        )
    job_store.update(job_id, status=JobStatus.DELETED.value)
    payload = DeletionPayload(job_id=job_id)
    deletion_sender.send(payload.model_dump_json())
    logger.info("job_id=%s marked deleted, deletion message sent", job_id)
    return RedirectResponse(url="/jobs?removed=1", status_code=303)
