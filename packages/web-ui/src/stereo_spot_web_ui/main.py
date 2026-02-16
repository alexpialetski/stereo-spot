"""FastAPI app: server-rendered pages for dashboard, jobs, create, detail, play."""

import base64
import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from stereo_spot_shared import Job, JobStatus, JobStore, ObjectStorage, StereoMode

from .deps import (
    get_input_bucket,
    get_job_store,
    get_object_storage,
    get_output_bucket,
)

logger = logging.getLogger(__name__)

# Keys per ARCHITECTURE: input/{job_id}/source.mp4, jobs/{job_id}/final.mp4
INPUT_KEY_TEMPLATE = "input/{job_id}/source.mp4"
OUTPUT_FINAL_KEY_TEMPLATE = "jobs/{job_id}/final.mp4"

app = FastAPI(title="Stereo-Spot Web UI", version="0.1.0")

templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


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
    """List completed jobs (GSI status=completed, descending completed_at)."""
    exclusive_start_key = None
    if next_token:
        try:
            raw = base64.urlsafe_b64decode(next_token.encode())
            exclusive_start_key = json.loads(raw.decode())
        except Exception:
            exclusive_start_key = None
    items, next_key = job_store.list_completed(limit=limit, exclusive_start_key=exclusive_start_key)
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
            "jobs": items,
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


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
    object_storage: ObjectStorage = Depends(get_object_storage),
    input_bucket: str = Depends(get_input_bucket),
) -> HTMLResponse:
    """Job detail: upload URL + instructions if status=created; otherwise status."""
    job = job_store.get(job_id)
    if job is None:
        logger.warning("job_id=%s not found (detail)", job_id)
        return HTMLResponse(content="Job not found", status_code=404)
    logger.info("job_id=%s detail status=%s", job_id, job.status.value)
    upload_url = None
    if job.status == JobStatus.CREATED:
        input_key = INPUT_KEY_TEMPLATE.format(job_id=job_id)
        upload_url = object_storage.presign_upload(
            input_bucket, input_key, expires_in=3600
        )
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "request": request,
            "job": job,
            "upload_url": upload_url,
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
