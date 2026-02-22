"""Shared pure helpers for web-ui (no FastAPI app creation)."""

import re
import time
from pathlib import Path

from fastapi import FastAPI, Request
from stereo_spot_shared import Job, JobStatus, JobStore, SegmentCompletionStore

from .constants import ETA_CACHE_TTL_SEC, TITLE_MAX_LENGTH


def normalize_title_for_storage(raw: str) -> str:
    """Take basename, strip extension, sanitize for storage. Returns safe string or fallback."""
    path = Path(raw)
    base = path.stem or path.name
    if not base:
        base = path.name or "video"
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", base)
    safe = safe.strip("_") or "video"
    return safe[:TITLE_MAX_LENGTH]


def safe_download_filename(title: str | None) -> str:
    """Build safe filename for Content-Disposition. If no title, return 'final.mp4'."""
    if not title or not title.strip():
        return "final.mp4"
    base = normalize_title_for_storage(title)
    return f"{base}3d.mp4"


def compute_progress(
    job: Job | None,
    segment_store: SegmentCompletionStore,
) -> tuple[int, str]:
    """
    Compute progress_percent (0-100) and stage_label from job and segment completions.
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
        pct = 25 + int(50 * segments_done / total)
        return min(75, pct), "Processing segments"
    if job.status == JobStatus.FAILED:
        return 0, "Failed"
    return 0, "Unknown"


def get_eta_seconds_per_mb(job_store: JobStore, app: FastAPI) -> float:
    """
    Return average conversion seconds per MB from recent completed jobs (lazy + TTL cache).
    Returns 0.0 when no data.
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


def build_m3u_line(title: str | None, job_id: str) -> str:
    """Single M3U entry: EXTINF line (caller adds presigned URL line)."""
    label = title or job_id
    return f"#EXTINF:-1,{label}\n"


def launch_urls(request: Request, m3u_path: str) -> tuple[str, str]:
    """Build absolute m3u_url and pot3d_url from request and M3U path (e.g. /playlist/abc.m3u)."""
    base = str(request.base_url).rstrip("/")
    m3u_url = base + m3u_path
    if "://" in base:
        _, rest = base.split("://", 1)
        pot3d_url = "pot3d://" + rest.rstrip("/") + m3u_path
    else:
        pot3d_url = "pot3d://" + m3u_path.lstrip("/")
    return m3u_url, pot3d_url
