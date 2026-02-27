"""Tests for stream router: create session, end session, playlist."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from stereo_spot_web_ui.main import app


@pytest.fixture
def mock_stream_store():
    """In-memory stream sessions store for tests."""
    store = MagicMock()
    store.get.return_value = None
    store.put.side_effect = None
    store.set_ended_at.side_effect = None
    return store


@pytest.fixture
def client_with_stream_store(app_with_mocks, mock_stream_store):
    """TestClient with stream_sessions_store (app_with_mocks sets buckets and object_storage)."""
    app.state.stream_sessions_store = mock_stream_store
    yield TestClient(app)
    if hasattr(app.state, "stream_sessions_store"):
        del app.state.stream_sessions_store


def test_create_stream_session_returns_session_id_and_upload(client_with_stream_store, mock_stream_store):
    """POST /stream_sessions returns session_id, playlist_url, upload credentials."""
    with patch("stereo_spot_web_ui.routers.stream.boto3") as boto3_mock:
        sts = MagicMock()
        sts.get_federation_token.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
                "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "SessionToken": "FQoGZXIvYXdzE...",
                "Expiration": __import__("datetime").datetime(2025, 1, 1, 12, 0),
            }
        }
        boto3_mock.client.return_value = sts
        resp = client_with_stream_store.post(
            "/stream_sessions",
            json={"mode": "sbs"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "playlist_url" in data
    assert "upload" in data
    assert data["upload"]["access_key_id"] == "AKIAIOSFODNN7EXAMPLE"
    assert data["upload"]["bucket"]
    assert "/stream/" in data["playlist_url"]
    assert data["playlist_url"].endswith("/playlist.m3u8")
    mock_stream_store.put.assert_called_once()
    pos = mock_stream_store.put.call_args[0]
    assert pos[2] == "sbs"  # mode is third positional
    assert mock_stream_store.put.call_args[1].get("ended_at") is None


def test_create_stream_session_rejects_invalid_mode(client_with_stream_store):
    """POST /stream_sessions with invalid mode returns 400."""
    resp = client_with_stream_store.post(
        "/stream_sessions",
        json={"mode": "invalid"},
    )
    assert resp.status_code == 400


def test_end_stream_session_204(client_with_stream_store, mock_stream_store):
    """POST /stream_sessions/{id}/end returns 204 and calls set_ended_at."""
    resp = client_with_stream_store.post("/stream_sessions/test-session/end")
    assert resp.status_code == 204
    mock_stream_store.set_ended_at.assert_called_once()
    assert mock_stream_store.set_ended_at.call_args[0][0] == "test-session"
    assert "T" in mock_stream_store.set_ended_at.call_args[0][1]  # ISO timestamp


def test_end_stream_session_invalid_id_400(client_with_stream_store):
    """POST /stream_sessions/{id}/end with invalid id (disallowed char) returns 400."""
    resp = client_with_stream_store.post("/stream_sessions/foo!bar/end")
    assert resp.status_code == 400


def test_playlist_invalid_session_id_400(client_with_stream_store):
    """GET /stream/{id}/playlist.m3u8 with invalid id (disallowed char) returns 400."""
    resp = client_with_stream_store.get("/stream/foo!bar/playlist.m3u8")
    assert resp.status_code == 400


def test_playlist_session_not_found_404(client_with_stream_store, mock_stream_store):
    """GET /stream/{id}/playlist.m3u8 returns 404 when store has no session."""
    mock_stream_store.get.return_value = None
    resp = client_with_stream_store.get("/stream/unknown-session/playlist.m3u8")
    assert resp.status_code == 404
