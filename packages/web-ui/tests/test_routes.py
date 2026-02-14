"""Unit tests for web-ui routes: create job, list, play URL."""

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


def test_list_endpoint_returns_only_completed(client: TestClient) -> None:
    """List jobs returns only completed jobs (GSI status=completed)."""
    store = app.state.job_store
    store.put(
        Job(
            job_id="created-job",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
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
    assert "created-job" not in response.text


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


def test_dashboard_and_jobs_list_render(client: TestClient) -> None:
    """Dashboard and jobs list return HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Stereo-Spot" in r.text
    assert "Create" in r.text or "create" in r.text

    r2 = client.get("/jobs")
    assert r2.status_code == 200
    assert "Completed" in r2.text or "jobs" in r2.text
