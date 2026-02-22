"""
Ingest loop: receive URL from queue, download (e.g. yt-dlp), upload to S3, update job.

Sets job title, uploaded_at, source_file_size_bytes and status=created so chunking
and ETA/analytics behave the same as the upload path.
"""

import json
import logging
import os
import re
import tempfile
import time

from stereo_spot_shared import JobStatus, YoutubeIngestPayload, parse_ingest_payload
from stereo_spot_shared.interfaces import JobStore, ObjectStorage, QueueReceiver

logger = logging.getLogger(__name__)

INPUT_KEY_TEMPLATE = "input/{job_id}/source.mp4"
TITLE_MAX_LENGTH = 200

# Cap resolution for YouTube ingest (e.g. 1080 = Full HD). Set MAX_VIDEO_HEIGHT env to override.
try:
    MAX_VIDEO_HEIGHT = int(os.environ.get("MAX_VIDEO_HEIGHT", "1080"))
except (TypeError, ValueError):
    MAX_VIDEO_HEIGHT = 1080


def _normalize_title(raw: str) -> str:
    """Sanitize title for storage (alphanumeric, underscore, hyphen; max length)."""
    if not raw or not raw.strip():
        return "video"
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw.strip())
    safe = safe.strip("_") or "video"
    return safe[:TITLE_MAX_LENGTH]


def _parse_ingest_body(body: str | bytes) -> YoutubeIngestPayload | None:
    """Parse queue message body as ingest payload. None if invalid."""
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    try:
        data = json.loads(body)
        return parse_ingest_payload(data)
    except json.JSONDecodeError:
        return None


def _is_video_format(f: dict) -> bool:
    vc = f.get("vcodec") or ""
    return vc != "none" and bool(vc)


def _is_audio_format(f: dict) -> bool:
    ac = f.get("acodec") or ""
    return ac != "none" and bool(ac)


def _is_combined_format(f: dict) -> bool:
    return _is_video_format(f) and _is_audio_format(f)


def _filter_formats_by_max_height(formats: list[dict], max_height: int) -> list[dict]:
    """Keep only formats with video height <= max_height (e.g. 1080 for Full HD cap)."""
    return [f for f in formats if int(f.get("height") or 0) <= max_height]


def _choose_format(formats: list[dict]) -> str | None:
    """
    Pick a format selector from actual available formats to avoid "format not available".
    Prefer: combined mp4 -> video+audio (merge to mp4) -> combined any -> single video.
    """
    if not formats:
        return None
    combined = [f for f in formats if _is_combined_format(f)]
    video_only = [f for f in formats if _is_video_format(f) and not _is_audio_format(f)]
    audio_only = [f for f in formats if _is_audio_format(f) and not _is_video_format(f)]

    # Prefer combined with ext mp4
    combined_mp4 = [f for f in combined if (f.get("ext") or "").lower() == "mp4"]
    if combined_mp4:
        best = max(combined_mp4, key=lambda x: int(x.get("height") or 0))
        return str(best.get("format_id", ""))

    # Prefer video + audio (yt-dlp will merge; we set merge_output_format mp4)
    if video_only and audio_only:
        best_v = max(video_only, key=lambda x: int(x.get("height") or 0))
        best_a = max(audio_only, key=lambda x: float(x.get("tbr") or 0))
        return f"{best_v.get('format_id')}+{best_a.get('format_id')}"

    # Any combined format
    if combined:
        best = max(combined, key=lambda x: int(x.get("height") or 0))
        return str(best.get("format_id", ""))

    # Single format with video
    with_video = [f for f in formats if _is_video_format(f)]
    if with_video:
        best = max(with_video, key=lambda x: int(x.get("height") or 0))
        return str(best.get("format_id", ""))

    return None


def _choose_format_dicts(formats: list[dict]) -> list[dict]:
    """
    Same logic as _choose_format but returns the actual format dict(s) for yt-dlp.
    Returns list of one dict (single/combined) or two dicts (video+audio to merge).
    """
    if not formats:
        return []
    combined = [f for f in formats if _is_combined_format(f)]
    video_only = [f for f in formats if _is_video_format(f) and not _is_audio_format(f)]
    audio_only = [f for f in formats if _is_audio_format(f) and not _is_video_format(f)]

    combined_mp4 = [f for f in combined if (f.get("ext") or "").lower() == "mp4"]
    if combined_mp4:
        best = max(combined_mp4, key=lambda x: int(x.get("height") or 0))
        return [best]

    if video_only and audio_only:
        best_v = max(video_only, key=lambda x: int(x.get("height") or 0))
        best_a = max(audio_only, key=lambda x: float(x.get("tbr") or 0))
        return [best_v, best_a]

    if combined:
        best = max(combined, key=lambda x: int(x.get("height") or 0))
        return [best]

    with_video = [f for f in formats if _is_video_format(f)]
    if with_video:
        best = max(with_video, key=lambda x: int(x.get("height") or 0))
        return [best]

    return []


def _format_selector_from_formats(
    info_dict: dict, *args: object, **kwargs: object
) -> list[dict]:
    """
    Custom format selector for yt-dlp: choose from actual formats so selection never fails.
    Used in Phase 1 (list formats). Returns list of format dict(s) for yt-dlp.
    Caps resolution at MAX_VIDEO_HEIGHT (default 1080p).
    """
    formats = info_dict.get("formats") or []
    formats = _filter_formats_by_max_height(formats, MAX_VIDEO_HEIGHT)
    chosen = _choose_format_dicts(formats)
    if chosen:
        return chosen
    if formats:
        return [formats[0]]
    return []


def _download_with_ytdlp(
    source_url: str, tmpdir: str
) -> tuple[str | None, str | None, str | None]:
    """
    Download video from URL using yt-dlp into tmpdir.
    Returns (filepath, title, error_message). On success error_message is None.
    Uses two-phase: list formats with custom selector then download with chosen format.
    """
    try:
        import yt_dlp
    except ImportError:
        return None, None, "yt-dlp not installed"

    outtmpl = os.path.join(tmpdir, "source.%(ext)s")
    base_opts: dict = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": "default,-tv_downgraded"}},
    }
    cookiefile = os.environ.get("YTDLP_COOKIES_PATH")
    if cookiefile and os.path.isfile(cookiefile):
        base_opts["cookiefile"] = cookiefile

    try:
        # Phase 1: list formats (no download); custom selector picks from actual list
        logger.info("ingest: listing formats for url=%s", source_url)
        list_opts = {**base_opts, "format": _format_selector_from_formats}
        with yt_dlp.YoutubeDL(list_opts) as ydl:
            info = ydl.extract_info(source_url, download=False)
        if not info:
            return None, None, "No info from yt-dlp"
        title = info.get("title") or "video"
        formats_raw = info.get("formats") or []
        sample = [
            (f.get("format_id"), f.get("height"), (f.get("vcodec") or "none")[:4])
            for f in formats_raw[:12]
        ]
        logger.info(
            "ingest: got %s formats (sample: %s)",
            len(formats_raw),
            sample,
        )
        formats = _filter_formats_by_max_height(formats_raw, MAX_VIDEO_HEIGHT)
        logger.info(
            "ingest: after height<=%s filter: %s formats",
            MAX_VIDEO_HEIGHT,
            len(formats),
        )
        chosen = _choose_format(formats)
        if chosen is None and formats_raw:
            chosen = _choose_format(formats_raw)
            if chosen is not None:
                logger.info(
                    "ingest: no format within cap, using best available (format=%s)",
                    chosen,
                )
        logger.debug("ingest: chosen=%s", chosen or "(none)")
        if not chosen:
            return None, None, "No suitable format available for this video"

        # Phase 2: download with chosen format
        logger.info("ingest: downloading with format=%s", chosen)
        need_merge = "+" in chosen
        download_opts = {
            **base_opts,
            "format": chosen,
            "merge_output_format": "mp4" if need_merge else None,
        }
        if download_opts["merge_output_format"] is None:
            del download_opts["merge_output_format"]
        with yt_dlp.YoutubeDL(download_opts) as ydl:
            info = ydl.extract_info(source_url, download=True)
            if not info:
                return None, None, "No info from yt-dlp after download"
            filepath = ydl.prepare_filename(info)
        if not filepath or not os.path.isfile(filepath):
            return None, None, "Downloaded file not found"
        return filepath, title, None
    except Exception as e:
        logger.exception("ingest: yt-dlp failed for %s: %s", source_url, e)
        return None, None, str(e)


def process_one_ingest_message(
    payload_str: str | bytes,
    job_store: JobStore,
    storage: ObjectStorage,
    input_bucket: str,
) -> bool:
    """
    Process a single ingest queue message.

    Returns True if the message was processed (success or skip/delete),
    False only on unexpected failure.
    """
    payload = _parse_ingest_body(payload_str)
    if payload is None:
        logger.warning("ingest: invalid message body")
        return True
    job_id = payload.job_id
    job = job_store.get(job_id)
    if job is None:
        logger.warning("ingest: job_id=%s not found", job_id)
        return True
    if job.status != JobStatus.CREATED:
        logger.info("ingest: job_id=%s skip (status=%s)", job_id, job.status.value)
        return True

    if isinstance(payload, YoutubeIngestPayload):
        source_url = payload.source_url
    else:
        logger.warning(
            "ingest: job_id=%s unsupported source_type=%s",
            job_id,
            getattr(payload, "source_type", "?"),
        )
        return True

    logger.info("ingest: job_id=%s start source_url=%s", job_id, source_url)
    job_store.update(job_id, status=JobStatus.INGESTING.value)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath, title, err = _download_with_ytdlp(source_url, tmpdir)
            if err:
                logger.warning("ingest: job_id=%s download failed: %s", job_id, err)
                job_store.update(job_id, status=JobStatus.FAILED.value)
                return True
            assert filepath is not None
            with open(filepath, "rb") as f:
                source_bytes = f.read()
            size = len(source_bytes)
            input_key = INPUT_KEY_TEMPLATE.format(job_id=job_id)
            storage.upload(input_bucket, input_key, source_bytes)
        now = int(time.time())
        normalized_title = _normalize_title(title) if title else "video"
        job_store.update(
            job_id,
            status=JobStatus.CREATED.value,
            uploaded_at=now,
            source_file_size_bytes=size,
            title=normalized_title,
        )
        logger.info(
            "ingest: job_id=%s complete title=%s size=%s",
            job_id,
            normalized_title,
            size,
        )
        return True
    except Exception as e:
        logger.exception("ingest: job_id=%s failed: %s", job_id, e)
        job_store.update(job_id, status=JobStatus.FAILED.value)
        return True


def run_ingest_loop(
    receiver: QueueReceiver,
    job_store: JobStore,
    storage: ObjectStorage,
    input_bucket: str,
    *,
    poll_interval_sec: float = 5.0,
) -> None:
    """Long-running loop: receive from ingest queue, process each, delete on success."""
    logger.info("ingest loop started")
    while True:
        messages = receiver.receive(max_messages=1)
        if messages:
            logger.debug("ingest: received %s message(s)", len(messages))
        for msg in messages:
            try:
                ok = process_one_ingest_message(
                    msg.body,
                    job_store,
                    storage,
                    input_bucket,
                )
                if ok:
                    receiver.delete(msg.receipt_handle)
            except Exception as e:
                logger.exception("ingest: failed to process message: %s", e)
        if not messages:
            time.sleep(poll_interval_sec)
