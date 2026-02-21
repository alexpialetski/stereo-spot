"""FastAPI app: server-rendered pages for dashboard, jobs, create, detail, play."""

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
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
)
from stereo_spot_shared.interfaces import OperatorLinksProvider, QueueSender

from .config import bootstrap_env
from .deps import (
    get_deletion_queue_sender,
    get_input_bucket,
    get_job_store,
    get_object_storage,
    get_operator_links_provider,
    get_output_bucket,
    get_segment_completion_store,
)

# Load .env from STEREOSPOT_ENV_FILE if set (e.g. by nx run web-ui:serve). Unset in ECS.
bootstrap_env()

# Ensure app loggers (e.g. events stream) emit INFO; uvicorn --log-level only affects uvicorn.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Keys per ARCHITECTURE: input/{job_id}/source.mp4, jobs/{job_id}/final.mp4
INPUT_KEY_TEMPLATE = "input/{job_id}/source.mp4"
OUTPUT_FINAL_KEY_TEMPLATE = "jobs/{job_id}/final.mp4"

app = FastAPI(title="Stereo-Spot Web UI", version="0.1.0")

_package_dir = Path(__file__).resolve().parent
templates_dir = _package_dir / "templates"
static_dir = _package_dir / "static"


def _cost_explorer_context(request: Request) -> dict:
    """Inject cost_explorer_url into all templates (from OperatorLinksProvider when available)."""
    provider = get_operator_links_provider(request)
    url = provider.get_cost_dashboard_url() if provider else None
    return {"cost_explorer_url": url}


templates = Jinja2Templates(
    directory=str(templates_dir),
    context_processors=[_cost_explorer_context],
)

# SSE poll interval, keepalive, and max stream duration
PROGRESS_POLL_SEC = 2
PROGRESS_KEEPALIVE_SEC = 30  # Send SSE comment so ALB/proxy does not close idle connection
PROGRESS_STREAM_TIMEOUT_SEC = 600  # 10 min

# Title: max length for storage and for Content-Disposition filename
TITLE_MAX_LENGTH = 200

# ETA cache TTL (seconds)
ETA_CACHE_TTL_SEC = 300


def _normalize_title_for_storage(raw: str) -> str:
    """Take basename, strip extension, sanitize for storage. Returns safe string or fallback."""
    path = Path(raw)
    base = path.stem or path.name  # stem = name without extension
    if not base:
        base = path.name or "video"
    # Keep only alphanumeric, hyphen, underscore; replace others with underscore
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", base)
    safe = safe.strip("_") or "video"
    return safe[:TITLE_MAX_LENGTH]


def _safe_download_filename(title: str | None) -> str:
    """Build safe filename for Content-Disposition. If no title, return 'final.mp4'."""
    if not title or not title.strip():
        return "final.mp4"
    base = _normalize_title_for_storage(title)
    return f"{base}3d.mp4"


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


def _get_eta_seconds_per_mb(job_store: JobStore, app: FastAPI) -> float:
    """
    Return average conversion seconds per MB from recent completed jobs (lazy + TTL cache).
    Used for ETA and countdown; returns 0.0 when no data.
    """
    cached = getattr(app.state, "eta_seconds_per_mb_cached", None)
    cached_at = getattr(app.state, "eta_seconds_per_mb_cached_at", 0)
    if cached is not None and (time.time() - cached_at) < ETA_CACHE_TTL_SEC:
        return cached
    items, _ = job_store.list_completed(limit=50)
    sec_per_mb_list = []
    for item in items:
        if (
            item.uploaded_at is not None
            and item.source_file_size_bytes is not None
            and item.source_file_size_bytes > 0
        ):
            duration_sec = item.completed_at - item.uploaded_at
            if duration_sec > 0:
                mb = item.source_file_size_bytes / 1e6
                sec_per_mb_list.append(duration_sec / mb)
    if not sec_per_mb_list:
        value = 0.0
    else:
        value = sum(sec_per_mb_list) / len(sec_per_mb_list)
    app.state.eta_seconds_per_mb_cached = value
    app.state.eta_seconds_per_mb_cached_at = time.time()
    return value


def _compute_progress(
    job: Job | None,
    segment_store: SegmentCompletionStore,
) -> tuple[int, str]:
    """
    Compute progress_percent (0-100) and stage_label from job and segment completions.
    Backend owns the semantics; UI just displays the numbers.
    """
    if job is None:
        return 0, "Unknown"
    if job.status == JobStatus.COMPLETED:
        return 100, "Completed"
    if job.status == JobStatus.CREATED:
        return 5, "Waiting for upload"
    if job.status == JobStatus.CHUNKING_IN_PROGRESS:
        return 15, "Chunking video"
    if job.status == JobStatus.CHUNKING_COMPLETE:
        total = job.total_segments or 0
        if total <= 0:
            return 50, "Processing segments"
        completions = segment_store.query_by_job(job.job_id)
        segments_done = len(completions)
        # 25% .. 75% for segment phase
        pct = 25 + int(50 * segments_done / total)
        return min(75, pct), "Processing segments"
    if job.status == JobStatus.FAILED:
        return 0, "Failed"
    return 0, "Unknown"


app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Dashboard: welcome and link to create job / list jobs."""
    return templates.TemplateResponse(request, "dashboard.html", {"request": request})


@app.get("/jobs", response_class=HTMLResponse)
async def list_jobs(
    request: Request,
    job_store: JobStore = Depends(get_job_store),
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


@app.post("/jobs")
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


@app.patch("/jobs/{job_id}", status_code=204)
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
    normalized = _normalize_title_for_storage(body.title)
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


@app.get("/jobs/{job_id}/events")
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
        logger.info("job_id=%s events stream started", job_id)
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
                percent, label = _compute_progress(job, segment_store)
                # Send event when value changed or first time
                if percent != last_percent or label != last_label:
                    last_percent = percent
                    last_label = label
                    payload = {"progress_percent": percent, "stage_label": label}
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_keepalive = time.monotonic()
                # Keepalive so ALB/proxy does not close connection during long segment processing
                elif time.monotonic() - last_keepalive >= PROGRESS_KEEPALIVE_SEC:
                    yield ": keepalive\n\n"
                    last_keepalive = time.monotonic()
                if job.status == JobStatus.COMPLETED:
                    if last_percent != 100 or last_label != "Completed":
                        payload = {"progress_percent": 100, "stage_label": "Completed"}
                        yield f"data: {json.dumps(payload)}\n\n"
                    logger.info("job_id=%s events stream ended (completed)", job_id)
                    return
                await asyncio.sleep(PROGRESS_POLL_SEC)
            logger.info("job_id=%s events stream ended (timeout)", job_id)
        except asyncio.CancelledError:
            logger.info("job_id=%s events stream ended (client disconnect)", job_id)
            raise

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
    object_storage: ObjectStorage = Depends(get_object_storage),
    segment_store: SegmentCompletionStore = Depends(get_segment_completion_store),
    input_bucket: str = Depends(get_input_bucket),
    output_bucket: str = Depends(get_output_bucket),
    operator_links: OperatorLinksProvider | None = Depends(get_operator_links_provider),
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
    if job.status == JobStatus.COMPLETED:
        key = OUTPUT_FINAL_KEY_TEMPLATE.format(job_id=job_id)
        playback_url = object_storage.presign_download(
            output_bucket, key, expires_in=3600
        )
        download_filename = _safe_download_filename(job.title)
        download_url = object_storage.presign_download(
            output_bucket,
            key,
            expires_in=3600,
            response_content_disposition=f'attachment; filename="{download_filename}"',
        )
    progress_percent, stage_label = _compute_progress(job, segment_store)
    eta_seconds_per_mb = _get_eta_seconds_per_mb(job_store, request.app)
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


@app.get("/jobs/{job_id}/play", response_model=None)
async def play(
    request: Request,
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
        output_bucket, key, expires_in=3600
    )
    return RedirectResponse(url=playback_url, status_code=302)


@app.post("/jobs/{job_id}/delete", response_model=None)
async def delete_job(
    request: Request,
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
