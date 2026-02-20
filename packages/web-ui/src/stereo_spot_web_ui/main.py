"""FastAPI app: server-rendered pages for dashboard, jobs, create, detail, play."""

import asyncio
import base64
import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from stereo_spot_shared import (
    Job,
    JobStatus,
    JobStore,
    ObjectStorage,
    SegmentCompletionStore,
    StereoMode,
)

from .config import bootstrap_env, get_settings
from .deps import (
    get_input_bucket,
    get_job_store,
    get_object_storage,
    get_output_bucket,
    get_segment_completion_store,
)

# Load .env from STEREOSPOT_ENV_FILE if set (e.g. by nx run web-ui:serve). Unset in ECS.
bootstrap_env()

logger = logging.getLogger(__name__)

# Keys per ARCHITECTURE: input/{job_id}/source.mp4, jobs/{job_id}/final.mp4
INPUT_KEY_TEMPLATE = "input/{job_id}/source.mp4"
OUTPUT_FINAL_KEY_TEMPLATE = "jobs/{job_id}/final.mp4"

app = FastAPI(title="Stereo-Spot Web UI", version="0.1.0")

_package_dir = Path(__file__).resolve().parent
templates_dir = _package_dir / "templates"
static_dir = _package_dir / "static"
templates = Jinja2Templates(directory=str(templates_dir))

# SSE poll interval, keepalive, and max stream duration
PROGRESS_POLL_SEC = 2
PROGRESS_KEEPALIVE_SEC = 30  # Send SSE comment so ALB/proxy does not close idle connection
PROGRESS_STREAM_TIMEOUT_SEC = 600  # 10 min


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
    return templates.TemplateResponse(
        request,
        "jobs_list.html",
        {
            "request": request,
            "in_progress_jobs": in_progress,
            "completed_jobs": completed_items,
            "next_token": next_token_out,
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
        start = time.monotonic()
        last_keepalive = start
        last_percent = -1
        last_label = ""
        while (time.monotonic() - start) < PROGRESS_STREAM_TIMEOUT_SEC:
            job = job_store.get(job_id, consistent_read=True)
            if job is None:
                logger.warning("job_id=%s events stream: job not found", job_id)
                yield f"data: {json.dumps({'progress_percent': 0, 'stage_label': 'Not found'})}\n\n"
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
) -> HTMLResponse:
    """Job detail: upload URL + instructions if status=created; otherwise status + progress."""
    job = job_store.get(job_id)
    if job is None:
        logger.warning("job_id=%s not found (detail)", job_id)
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
        download_url = object_storage.presign_download(
            output_bucket,
            key,
            expires_in=3600,
            response_content_disposition='attachment; filename="final.mp4"',
        )
    progress_percent, stage_label = _compute_progress(job, segment_store)
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
            "settings": get_settings(),
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
