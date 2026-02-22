"""Tests for launch router: playlist, setup/windows, launch pages."""

from fastapi.testclient import TestClient
from stereo_spot_shared import Job, JobStatus, StereoMode

from stereo_spot_web_ui.constants import PLAYBACK_PRESIGN_EXPIRY_SEC
from stereo_spot_web_ui.main import app


def test_playlist_single_m3u_returns_m3u_with_presigned_url(client: TestClient) -> None:
    """GET /playlist/{job_id}.m3u returns M3U with one entry and presigned URL."""
    store = app.state.job_store
    job_id = "m3u-job-1"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            completed_at=1000,
            title="my-video",
        )
    )
    response = client.get(f"/playlist/{job_id}.m3u")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-mpegurl"
    assert "#EXTM3U" in response.text
    assert "#EXTINF" in response.text
    assert f"jobs/{job_id}/final.mp4" in response.text
    assert f"expires={PLAYBACK_PRESIGN_EXPIRY_SEC}" in response.text
    assert "my-video" in response.text


def test_playlist_single_returns_404_when_job_missing(client: TestClient) -> None:
    """GET /playlist/{job_id}.m3u returns 404 when job does not exist."""
    response = client.get("/playlist/nonexistent.m3u")
    assert response.status_code == 404


def test_playlist_single_returns_400_when_job_not_completed(client: TestClient) -> None:
    """GET /playlist/{job_id}.m3u returns 400 when job is not completed."""
    store = app.state.job_store
    job_id = "pending-m3u"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.CHUNKING_IN_PROGRESS,
        )
    )
    response = client.get(f"/playlist/{job_id}.m3u")
    assert response.status_code == 400
    assert "not completed" in response.text


def test_playlist_all_m3u_returns_m3u_with_long_expiry(client: TestClient) -> None:
    """GET /playlist.m3u returns M3U and presigned URLs use playback expiry."""
    store = app.state.job_store
    store.put(
        Job(
            job_id="done-a",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            completed_at=2000,
        )
    )
    response = client.get("/playlist.m3u")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-mpegurl"
    assert "#EXTM3U" in response.text
    assert f"expires={PLAYBACK_PRESIGN_EXPIRY_SEC}" in response.text


def test_setup_windows_returns_404_when_exe_missing(client: TestClient) -> None:
    """GET /setup/windows returns 404 when EXE file is not present (e.g. local dev)."""
    response = client.get("/setup/windows")
    assert response.status_code == 404
    assert "not available" in response.text or "404" in response.text


def test_launch_single_returns_200_and_urls(client: TestClient) -> None:
    """GET /launch/{job_id} for completed job returns launch page with m3u_url and pot3d_url."""
    store = app.state.job_store
    job_id = "launch-job-1"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.COMPLETED,
            completed_at=1000,
        )
    )
    response = client.get(f"/launch/{job_id}")
    assert response.status_code == 200
    assert f"/playlist/{job_id}.m3u" in response.text
    assert "pot3d://" in response.text
    assert "/setup/windows" in response.text


def test_launch_single_returns_404_when_job_missing(client: TestClient) -> None:
    """GET /launch/{job_id} returns 404 when job does not exist."""
    response = client.get("/launch/nonexistent")
    assert response.status_code == 404


def test_launch_single_returns_400_when_not_completed(client: TestClient) -> None:
    """GET /launch/{job_id} returns 400 when job is not completed."""
    store = app.state.job_store
    job_id = "pending-launch"
    store.put(
        Job(
            job_id=job_id,
            mode=StereoMode.SBS,
            status=JobStatus.CHUNKING_IN_PROGRESS,
        )
    )
    response = client.get(f"/launch/{job_id}")
    assert response.status_code == 400


def test_launch_all_returns_200_with_playlist_m3u(client: TestClient) -> None:
    """GET /launch returns launch page with playlist.m3u URLs."""
    response = client.get("/launch")
    assert response.status_code == 200
    assert "/playlist.m3u" in response.text
    assert "pot3d://" in response.text
