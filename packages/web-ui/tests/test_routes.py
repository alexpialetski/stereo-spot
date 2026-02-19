"""Unit tests for web-ui routes: create job, list, play URL."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from stereo_spot_shared import Job, JobStatus, StereoMode

from stereo_spot_web_ui.main import app


@pytest.fixture
def client(app_with_mocks: None) -> TestClient:
    return TestClient(app)


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


def test_job_detail_passes_eta_when_configured(client: TestClient) -> None:
    """Job detail includes ETA data attributes and message when ETA_SECONDS_PER_MB set."""
    store = app.state.job_store
    job_id = "eta-job"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
            created_at=100,
        )
    )
    with patch.dict("os.environ", {"ETA_SECONDS_PER_MB": "5", "ETA_CLOUD_NAME": "aws"}):
        response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "data-eta-seconds-per-mb" in response.text
    assert "data-eta-cloud" in response.text
    assert "eta-message" in response.text
    assert "5" in response.text
    assert "aws" in response.text


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
