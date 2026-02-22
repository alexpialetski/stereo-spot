"""Launch, playlist, and setup routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from stereo_spot_shared import JobStatus, JobStore, ObjectStorage

from ..constants import (
    DOCS_VIEWING_3D_URL,
    OUTPUT_FINAL_KEY_TEMPLATE,
    PLAYBACK_PRESIGN_EXPIRY_SEC,
    SETUP_EXE_FILENAME,
    STATIC_DIR,
)
from ..deps import get_job_store, get_object_storage, get_output_bucket, get_templates
from ..utils import build_m3u_line, launch_urls

router = APIRouter()


@router.get("/playlist/{path_item:path}", response_class=Response)
async def playlist_single(
    path_item: str,
    job_store: JobStore = Depends(get_job_store),
    object_storage: ObjectStorage = Depends(get_object_storage),
    output_bucket: str = Depends(get_output_bucket),
) -> Response:
    """Return M3U with one presigned URL for jobs/{job_id}/final.mp4.
    Path: /playlist/{job_id}.m3u."""
    job_id = path_item.removesuffix(".m3u") if path_item.endswith(".m3u") else path_item
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job not completed yet")
    key = OUTPUT_FINAL_KEY_TEMPLATE.format(job_id=job_id)
    url = object_storage.presign_download(
        output_bucket, key, expires_in=PLAYBACK_PRESIGN_EXPIRY_SEC
    )
    body = "#EXTM3U\n" + build_m3u_line(job.title, job_id) + url + "\n"
    return Response(
        content=body,
        media_type="application/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.m3u"'},
    )


@router.get("/playlist.m3u", response_class=Response)
async def playlist_all(
    job_store: JobStore = Depends(get_job_store),
    object_storage: ObjectStorage = Depends(get_object_storage),
    output_bucket: str = Depends(get_output_bucket),
    limit: int = 50,
) -> Response:
    """Return M3U with presigned URLs for all completed jobs (up to limit)."""
    completed_items, _ = job_store.list_completed(limit=limit, exclusive_start_key=None)
    lines = ["#EXTM3U"]
    for item in completed_items:
        key = OUTPUT_FINAL_KEY_TEMPLATE.format(job_id=item.job_id)
        url = object_storage.presign_download(
            output_bucket, key, expires_in=PLAYBACK_PRESIGN_EXPIRY_SEC
        )
        lines.append(build_m3u_line(item.title, item.job_id))
        lines.append(url)
    body = "\n".join(lines) + "\n"
    return Response(
        content=body,
        media_type="application/x-mpegurl",
        headers={"Content-Disposition": 'attachment; filename="playlist.m3u"'},
    )


@router.get("/launch/{job_id}", response_class=HTMLResponse)
async def launch_single(
    request: Request,
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Launch page for single video: redirect to pot3d:// or show fallback (EXE / M3U download)."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job not completed yet")
    m3u_path = f"/playlist/{job_id}.m3u"
    m3u_url, pot3d_url = launch_urls(request, m3u_path)
    return templates.TemplateResponse(
        request,
        "launch.html",
        {
            "request": request,
            "m3u_url": m3u_url,
            "pot3d_url": pot3d_url,
            "setup_exe_url": "/setup/windows",
            "docs_help_url": DOCS_VIEWING_3D_URL,
            "job_id": job_id,
            "title": job.title,
        },
    )


@router.get("/launch", response_class=HTMLResponse)
async def launch_all(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Launch page for all videos playlist: redirect to pot3d:// or show fallback."""
    m3u_path = "/playlist.m3u"
    m3u_url, pot3d_url = launch_urls(request, m3u_path)
    return templates.TemplateResponse(
        request,
        "launch.html",
        {
            "request": request,
            "m3u_url": m3u_url,
            "pot3d_url": pot3d_url,
            "setup_exe_url": "/setup/windows",
            "docs_help_url": DOCS_VIEWING_3D_URL,
            "job_id": None,
            "title": None,
        },
    )


@router.get("/setup/windows", response_class=Response)
async def setup_windows() -> Response:
    """Serve the 3D Linker setup EXE. 404 if file missing (e.g. local dev)."""
    exe_path = STATIC_DIR / SETUP_EXE_FILENAME
    if not exe_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Setup executable not available. Use the Docker image to get the EXE.",
        )
    return FileResponse(
        path=str(exe_path),
        filename=SETUP_EXE_FILENAME,
        media_type="application/octet-stream",
    )
