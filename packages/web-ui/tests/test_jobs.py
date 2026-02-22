"""Tests for jobs router: dashboard, list, create, detail, play, patch, delete, events."""

import json

import pytest
from fastapi.testclient import TestClient
from stereo_spot_shared import (
    Job,
    JobStatus,
    StereoMode,
    YoutubeIngestPayload,
    parse_ingest_payload,
)

from stereo_spot_web_ui.constants import PLAYBACK_PRESIGN_EXPIRY_SEC
from stereo_spot_web_ui.main import app
from stereo_spot_web_ui.utils import compute_progress


def test_create_job_returns_job_id_and_upload_url_with_correct_key(client: TestClient) -> None:
    """Create job returns job_id and upload URL with key input/{job_id}/source.mp4."""
    response = client.post("/jobs", data={"mode": "anaglyph"}, follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert "/jobs/" in location
    job_id = location.split("/jobs/")[1].rstrip("/")
    assert job_id

    # Follow redirect to job detail page
    detail = client.get(location)
    assert detail.status_code == 200
    # Upload URL must use key input/{job_id}/source.mp4
    assert f"input/{job_id}/source.mp4" in detail.text
    assert "mock-upload" in detail.text or "input-bucket" in detail.text


def test_create_job_from_url_creates_job_and_sends_to_ingest_queue(
    client: TestClient,
) -> None:
    """POST /jobs/from-url creates job and sends IngestPayload to ingest queue."""
    response = client.post(
        "/jobs/from-url",
        data={
            "mode": "sbs",
            "source_url": "https://www.youtube.com/watch?v=abc",
            "source_type": "youtube",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "/jobs/" in location
    job_id = location.split("/jobs/")[1].rstrip("/")
    assert job_id
    sender = app.state.ingest_queue_sender
    assert len(sender.sent) == 1
    payload = parse_ingest_payload(json.loads(sender.sent[0]))
    assert payload is not None
    assert isinstance(payload, YoutubeIngestPayload)
    assert payload.job_id == job_id
    assert payload.source_url == "https://www.youtube.com/watch?v=abc"
    assert payload.source_type == "youtube"
    store = app.state.job_store
    job = store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.CREATED


def test_create_job_from_url_rejects_invalid_url(client: TestClient) -> None:
    """POST /jobs/from-url returns 400 for non-YouTube URL."""
    response = client.post(
        "/jobs/from-url",
        data={"mode": "sbs", "source_url": "not-a-url"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "YouTube" in response.text or "supported" in response.text


def test_create_job_from_url_rejects_non_youtube_http_url(client: TestClient) -> None:
    """POST /jobs/from-url returns 400 for http(s) URL that is not YouTube."""
    response = client.post(
        "/jobs/from-url",
        data={"mode": "sbs", "source_url": "https://example.com/video"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "YouTube" in response.text or "supported" in response.text


def test_create_job_from_url_accepts_youtube_url_formats(client: TestClient) -> None:
    """POST /jobs/from-url accepts youtube.com/watch and youtu.be URLs."""
    from stereo_spot_web_ui.routers.jobs import _is_youtube_url

    assert _is_youtube_url("https://www.youtube.com/watch?v=z10mgByREbc") is True
    url_with_list = "https://www.youtube.com/watch?v=4N9HmMNf7EU&list=RD4N9HmMNf7EU&start_radio=1"
    assert _is_youtube_url(url_with_list) is True
    assert _is_youtube_url("https://youtu.be/4N9HmMNf7EU?si=fDoEEB4SFmYjohda") is True
    assert _is_youtube_url("https://example.com/v") is False
    assert _is_youtube_url("") is False


def test_ingest_from_url_queues_payload_job_stays_created(client: TestClient) -> None:
    """POST /jobs/{id}/ingest-from-url returns 204, sends payload; job stays CREATED."""
    store = app.state.job_store
    job_id = "created-for-ingest"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.CREATED,
            created_at=100,
        )
    )
    response = client.post(
        f"/jobs/{job_id}/ingest-from-url",
        json={"source_url": "https://www.youtube.com/watch?v=abc"},
    )
    assert response.status_code == 204
    sender = app.state.ingest_queue_sender
    assert len(sender.sent) == 1
    payload = parse_ingest_payload(json.loads(sender.sent[0]))
    assert payload is not None
    assert isinstance(payload, YoutubeIngestPayload)
    assert payload.job_id == job_id
    assert payload.source_url == "https://www.youtube.com/watch?v=abc"
    job = store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.CREATED


def test_ingest_from_url_returns_404_when_job_missing(client: TestClient) -> None:
    """POST /jobs/{id}/ingest-from-url returns 404 when job does not exist."""
    response = client.post(
        "/jobs/nonexistent-id/ingest-from-url",
        json={"source_url": "https://www.youtube.com/watch?v=abc"},
    )
    assert response.status_code == 404


def test_ingest_from_url_returns_400_when_job_not_created(client: TestClient) -> None:
    """POST /jobs/{id}/ingest-from-url returns 400 when job already has source."""
    store = app.state.job_store
    job_id = "completed-for-ingest"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.COMPLETED,
            created_at=100,
            completed_at=200,
        )
    )
    response = client.post(
        f"/jobs/{job_id}/ingest-from-url",
        json={"source_url": "https://www.youtube.com/watch?v=abc"},
    )
    assert response.status_code == 400
    assert "already" in response.text or "content" in response.text.lower()


def test_ingest_from_url_returns_400_for_invalid_url(client: TestClient) -> None:
    """POST /jobs/{id}/ingest-from-url returns 400 for non-YouTube URL."""
    store = app.state.job_store
    job_id = "created-bad-url"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.CREATED,
            created_at=100,
        )
    )
    response = client.post(
        f"/jobs/{job_id}/ingest-from-url",
        json={"source_url": "https://example.com/video"},
    )
    assert response.status_code == 400
    assert "YouTube" in response.text or "supported" in response.text


def test_job_detail_created_shows_upload_and_url_blocks(client: TestClient) -> None:
    """Job detail when CREATED shows side-by-side upload and paste URL options."""
    store = app.state.job_store
    job_id = "created-two-options"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.CREATED,
            created_at=100,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "Upload your video" in response.text
    assert "Or paste a video URL" in response.text
    assert "Fetch from URL" in response.text
    assert "source-url" in response.text
    assert "source-upload-block" in response.text
    assert "source-url-block" in response.text


def test_job_detail_ingesting_does_not_show_upload_block(client: TestClient) -> None:
    """Job detail with status ingesting does not show upload URL block."""
    store = app.state.job_store
    job_id = "ingesting-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.INGESTING,
            created_at=100,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    # Upload block is only shown when status is CREATED; INGESTING should not show it
    assert "Upload your video" not in response.text
    assert "Downloading source" in response.text


def test_compute_progress_ingesting_returns_downloading_label(
    client: TestClient,
) -> None:
    """compute_progress returns (5, 'Downloading source…') for INGESTING."""
    store = app.state.job_store
    job_id = "ing-progress"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.INGESTING,
            created_at=200,
        )
    )
    job = store.get(job_id)
    segment_store = app.state.segment_completion_store
    percent, label = compute_progress(job, segment_store)
    assert percent == 5
    assert label == "Downloading source…"


def test_list_endpoint_shows_in_progress_and_completed(client: TestClient) -> None:
    """List jobs shows in-progress and completed (both View) in respective sections."""
    store = app.state.job_store
    store.put(
        Job(
            job_id="created-job",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
            created_at=500,
        )
    )
    store.put(
        Job(
            job_id="completed-job",
            mode=StereoMode.SBS,
            status=JobStatus.COMPLETED,
            completed_at=1000,
        )
    )

    response = client.get("/jobs")
    assert response.status_code == 200
    assert "completed-job" in response.text
    assert "created-job" in response.text
    assert "In progress" in response.text
    assert "Completed" in response.text


def test_play_url_uses_correct_key(client: TestClient) -> None:
    """Play redirects to presigned URL for jobs/{job_id}/final.mp4 with playback expiry."""
    store = app.state.job_store
    job_id = "done-123"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            completed_at=2000,
        )
    )

    response = client.get(f"/jobs/{job_id}/play", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert f"jobs/{job_id}/final.mp4" in location
    assert "mock-download" in location or "output-bucket" in location
    assert f"expires={PLAYBACK_PRESIGN_EXPIRY_SEC}" in location


def test_play_returns_400_when_job_not_completed(client: TestClient) -> None:
    """Play returns 400 when job is not completed."""
    store = app.state.job_store
    job_id = "pending-456"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.CHUNKING_IN_PROGRESS,
        )
    )

    response = client.get(f"/jobs/{job_id}/play")
    assert response.status_code == 400
    assert "not completed" in response.text


def test_play_returns_404_when_job_missing(client: TestClient) -> None:
    """Play returns 404 when job does not exist."""
    response = client.get("/jobs/nonexistent-id/play")
    assert response.status_code == 404


def test_dashboard_and_jobs_list_render(client: TestClient) -> None:
    """Dashboard has single Create job form; jobs list returns HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Stereo-Spot" in r.text
    assert "Create job" in r.text
    assert "Create job from URL" not in r.text

    r2 = client.get("/jobs")
    assert r2.status_code == 200
    assert "Completed" in r2.text or "jobs" in r2.text


def test_job_detail_includes_progress(client: TestClient) -> None:
    """Job detail page includes progress bar and stage label when not completed."""
    store = app.state.job_store
    job_id = "progress-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CHUNKING_IN_PROGRESS,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "progress-bar" in response.text
    assert "Chunking video" in response.text


def test_job_detail_completed_shows_video_and_download(client: TestClient) -> None:
    """Job detail page shows video player and download link when completed."""
    store = app.state.job_store
    job_id = "done-789"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            completed_at=3000,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert '<video' in response.text
    assert "Download" in response.text


def test_job_detail_shows_eta_when_cache_has_data(client: TestClient) -> None:
    """Job detail includes ETA when cache is populated from completed jobs."""
    store = app.state.job_store
    # Populate cache: completed job with uploaded_at and source_file_size_bytes
    store.put(
        Job(
            job_id="completed-eta-source",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            created_at=100,
            completed_at=200,
            uploaded_at=105,
            source_file_size_bytes=10_000_000,
        )
    )
    job_id = "eta-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
            created_at=100,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "data-eta-seconds-per-mb" in response.text
    assert "eta-message" in response.text


def test_job_progress_events_stream(client: TestClient) -> None:
    """SSE endpoint streams progress_percent and stage_label."""
    store = app.state.job_store
    job_id = "events-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.COMPLETED,
            completed_at=1234,
        )
    )
    response = client.get(f"/jobs/{job_id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    # First event should be 100% Completed then stream ends
    text = response.text
    assert "100" in text
    assert "Completed" in text


def test_delete_job_returns_404_when_job_missing(client: TestClient) -> None:
    """POST /jobs/{id}/delete returns 404 when job does not exist."""
    response = client.post("/jobs/nonexistent-id/delete")
    assert response.status_code == 404


def test_delete_job_returns_400_when_not_completed_or_failed(client: TestClient) -> None:
    """POST /jobs/{id}/delete returns 400 when job is in progress."""
    store = app.state.job_store
    job_id = "in-progress-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CHUNKING_IN_PROGRESS,
            created_at=100,
        )
    )
    response = client.post(f"/jobs/{job_id}/delete")
    assert response.status_code == 400
    assert "Can only remove" in response.text


def test_delete_job_redirects_and_sends_message_when_completed(
    client: TestClient,
) -> None:
    """POST /jobs/{id}/delete marks job deleted, sends to queue, redirects with removed=1."""
    store = app.state.job_store
    sender = app.state.deletion_queue_sender
    job_id = "to-delete-completed"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            completed_at=2000,
        )
    )
    response = client.post(f"/jobs/{job_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/jobs?removed=1"
    job = store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.DELETED
    assert len(sender.sent) == 1
    body = sender.sent[0]
    assert job_id in (body.decode() if isinstance(body, bytes) else body)


def test_delete_job_allowed_when_failed(client: TestClient) -> None:
    """POST /jobs/{id}/delete is allowed when job status is failed."""
    store = app.state.job_store
    sender = app.state.deletion_queue_sender
    job_id = "to-delete-failed"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.FAILED,
            created_at=100,
        )
    )
    response = client.post(f"/jobs/{job_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert store.get(job_id).status == JobStatus.DELETED
    assert len(sender.sent) == 1


def test_job_detail_returns_404_when_deleted(client: TestClient) -> None:
    """GET /jobs/{id} returns 404 when job status is deleted."""
    store = app.state.job_store
    job_id = "deleted-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.DELETED,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 404


def test_patch_job_sets_title_and_timing(client: TestClient) -> None:
    """PATCH /jobs/{id} with title and source_file_size_bytes sets title, uploaded_at, size."""
    store = app.state.job_store
    job_id = "patch-title-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
            created_at=100,
        )
    )
    response = client.patch(
        f"/jobs/{job_id}",
        json={"title": "attack-on-titan.mp4", "source_file_size_bytes": 5_000_000},
    )
    assert response.status_code == 204
    job = store.get(job_id)
    assert job is not None
    assert job.title == "attack-on-titan"
    assert job.uploaded_at is not None
    assert job.source_file_size_bytes == 5_000_000
    detail = client.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    assert "attack-on-titan" in detail.text


def test_patch_job_returns_404_when_job_missing(client: TestClient) -> None:
    """PATCH /jobs/{id} returns 404 when job does not exist."""
    response = client.patch(
        "/jobs/nonexistent-id",
        json={"title": "foo.mp4"},
    )
    assert response.status_code == 404


def test_patch_job_returns_404_when_deleted(client: TestClient) -> None:
    """PATCH /jobs/{id} returns 404 when job is deleted."""
    store = app.state.job_store
    job_id = "deleted-patch-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.DELETED,
        )
    )
    response = client.patch(f"/jobs/{job_id}", json={"title": "foo.mp4"})
    assert response.status_code == 404


def test_job_detail_completed_with_title_shows_title(client: TestClient) -> None:
    """Completed job with title: detail page shows title and download link."""
    store = app.state.job_store
    job_id = "done-with-title"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            completed_at=3000,
            title="attack-on-titan",
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "attack-on-titan" in response.text
    assert "Download" in response.text


def test_job_detail_completed_shows_conversion_stats(client: TestClient) -> None:
    """Completed job with uploaded_at and source_file_size_bytes shows conversion time."""
    store = app.state.job_store
    job_id = "done-with-timing"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            created_at=100,
            completed_at=3000,
            uploaded_at=200,
            source_file_size_bytes=50_000_000,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "Conversion:" in response.text
    assert "sec/MB" in response.text


def test_job_detail_includes_open_logs_link_when_name_prefix_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Job detail shows Open logs link when NAME_PREFIX and region are set."""
    monkeypatch.setenv("NAME_PREFIX", "stereo-spot")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    store = app.state.job_store
    job_id = "logs-job-123"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "Open logs" in response.text
    assert job_id in response.text
    assert "stereo-spot" in response.text
    assert "cloudwatch" in response.text.lower()


def test_job_detail_no_open_logs_link_when_name_prefix_unset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Job detail does not show Open logs link when NAME_PREFIX is not set."""
    monkeypatch.delenv("NAME_PREFIX", raising=False)
    monkeypatch.delenv("LOGS_REGION", raising=False)
    store = app.state.job_store
    job_id = "no-logs-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
        )
    )
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "Open logs" not in response.text
