"""Unit tests for web-ui routes: create job, list, play URL."""

import pytest
from fastapi.testclient import TestClient
from stereo_spot_shared import Job, JobStatus, StereoMode

from stereo_spot_web_ui.main import (
    _normalize_title_for_storage,
    _safe_download_filename,
    app,
)


@pytest.fixture
def client(app_with_mocks: None) -> TestClient:
    return TestClient(app)


def test_normalize_title_for_storage() -> None:
    """Title normalization: basename, strip extension, safe chars."""
    assert _normalize_title_for_storage("attack-on-titan.mp4") == "attack-on-titan"
    assert _normalize_title_for_storage("/path/to/video.mp4") == "video"
    assert _normalize_title_for_storage("my video (1).mp4") == "my_video__1"


def test_safe_download_filename() -> None:
    """Download filename: title -> base3d.mp4; no title -> final.mp4."""
    assert _safe_download_filename("attack-on-titan") == "attack-on-titan3d.mp4"
    assert _safe_download_filename(None) == "final.mp4"
    assert _safe_download_filename("") == "final.mp4"


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
    """Play redirects to presigned URL for jobs/{job_id}/final.mp4."""
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


def test_static_favicon_served(client: TestClient) -> None:
    """Static files are served from /static."""
    response = client.get("/static/favicon.png", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_dashboard_and_jobs_list_render(client: TestClient) -> None:
    """Dashboard and jobs list return HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Stereo-Spot" in r.text
    assert "Create" in r.text or "create" in r.text

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
