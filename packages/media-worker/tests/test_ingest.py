"""Tests for ingest flow with mocked JobStore, ObjectStorage, and yt-dlp."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from stereo_spot_shared import Job, JobStatus, StereoMode, YoutubeIngestPayload

from media_worker.ingest import (
    _parse_ingest_body,
    process_one_ingest_message,
)


def test_parse_ingest_body_valid() -> None:
    """Valid JSON with source_type=youtube parses to YoutubeIngestPayload."""
    body = json.dumps({
        "source_type": "youtube",
        "job_id": "job-1",
        "source_url": "https://www.youtube.com/watch?v=abc",
    })
    payload = _parse_ingest_body(body)
    assert payload is not None
    assert isinstance(payload, YoutubeIngestPayload)
    assert payload.job_id == "job-1"
    assert payload.source_url == "https://www.youtube.com/watch?v=abc"
    assert payload.source_type == "youtube"


def test_parse_ingest_body_youtube_default_source_type() -> None:
    """YoutubeIngestPayload serialized includes source_type; parse accepts it."""
    body = json.dumps({"source_type": "youtube", "job_id": "j", "source_url": "https://x.com/v"})
    payload = _parse_ingest_body(body)
    assert payload is not None
    assert payload.source_type == "youtube"


def test_parse_ingest_body_invalid_returns_none() -> None:
    """Invalid JSON or missing fields returns None."""
    assert _parse_ingest_body("not json") is None
    assert _parse_ingest_body("{}") is None
    assert _parse_ingest_body(json.dumps({"job_id": "j"})) is None
    assert _parse_ingest_body(json.dumps({"source_url": "https://x"})) is None


def test_process_one_ingest_message_invalid_body_returns_true() -> None:
    """Invalid message body: return True (delete message), no job update."""
    store = MagicMock()
    storage = MagicMock()
    ok = process_one_ingest_message("invalid", store, storage, "input-bucket")
    assert ok is True
    store.get.assert_not_called()
    store.update.assert_not_called()


def test_process_one_ingest_message_job_not_found_returns_true() -> None:
    """Job not found: return True (delete message), no update."""
    store = MagicMock()
    store.get.return_value = None
    storage = MagicMock()
    body = json.dumps({
        "source_type": "youtube",
        "job_id": "missing",
        "source_url": "https://example.com/v",
    })
    ok = process_one_ingest_message(body, store, storage, "input-bucket")
    assert ok is True
    store.update.assert_not_called()


def test_process_one_ingest_message_job_wrong_status_returns_true() -> None:
    """Job status not CREATED: return True (skip), no download."""
    store = MagicMock()
    store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.SBS,
        status=JobStatus.CHUNKING_IN_PROGRESS,
        created_at=100,
    )
    storage = MagicMock()
    body = json.dumps({
        "source_type": "youtube",
        "job_id": "job-1",
        "source_url": "https://example.com/v",
    })
    ok = process_one_ingest_message(body, store, storage, "input-bucket")
    assert ok is True
    # Only get called, no status update to INGESTING (we skip)
    store.update.assert_not_called()


def test_process_one_ingest_message_success_updates_job_and_uploads(
    tmp_path: Path,
) -> None:
    """Valid message: download (mocked), upload to S3, update job with title/size/status=created."""
    job_id = "job-success"
    store = MagicMock()
    store.get.return_value = Job(
        job_id=job_id,
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CREATED,
        created_at=200,
    )
    storage = MagicMock()
    body = json.dumps({
        "source_type": "youtube",
        "job_id": job_id,
        "source_url": "https://www.youtube.com/watch?v=xyz",
    })
    fake_file = tmp_path / "source.mp4"
    fake_file.write_bytes(b"fake video content for upload")
    fake_title = "My Video Title"

    with patch(
        "media_worker.ingest._download_with_ytdlp",
        return_value=(str(fake_file), fake_title, None),
    ):
        ok = process_one_ingest_message(body, store, storage, "input-bucket")

    assert ok is True
    storage.upload.assert_called_once()
    call_args = storage.upload.call_args
    assert call_args[0][0] == "input-bucket"
    assert call_args[0][1] == f"input/{job_id}/source.mp4"
    assert call_args[0][2] == b"fake video content for upload"
    # Job: first update to INGESTING, then to CREATED with uploaded_at, size, title
    assert store.update.call_count >= 2
    # Last update should set status=created, uploaded_at, source_file_size_bytes, title
    last_call_kw = store.update.call_args[1]
    assert last_call_kw.get("status") == JobStatus.CREATED.value
    assert "uploaded_at" in last_call_kw
    assert last_call_kw.get("source_file_size_bytes") == len(b"fake video content for upload")
    assert last_call_kw.get("title") == "My_Video_Title"
