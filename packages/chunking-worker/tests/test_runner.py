"""Tests for chunking flow with mocked JobStore and ObjectStorage."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from stereo_spot_shared import Job, JobStatus, StereoMode

from chunking_worker.runner import process_one_message


def _make_s3_event_body(bucket: str, key: str) -> str:
    return json.dumps({
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                }
            }
        ]
    })


@pytest.fixture
def mock_job_store() -> MagicMock:
    store = MagicMock()
    store.get.return_value = Job(
        job_id="test-job",
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CREATED,
        created_at=12345,
    )
    return store


@pytest.fixture
def mock_storage() -> MagicMock:
    return MagicMock()


def test_process_one_message_mock_chunking_flow(
    mock_job_store: MagicMock,
    mock_storage: MagicMock,
    tmp_path: Path,
) -> None:
    """With chunk_video_to_temp patched to return two fake segments, process_one_message
    uploads both with canonical keys and updates job to chunking_complete with total_segments=2.
    """
    body = _make_s3_event_body("input-bucket", "input/test-job/source.mp4")
    mock_storage.download.return_value = b"fake source video bytes"

    seg0 = tmp_path / "segment_00000.mp4"
    seg1 = tmp_path / "segment_00001.mp4"
    seg0.write_bytes(b"seg0")
    seg1.write_bytes(b"seg1")
    fake_segments = [seg0, seg1]

    class FakeTmp:
        def cleanup(self) -> None:
            pass

    with patch(
        "chunking_worker.runner.chunk_video_to_temp",
        return_value=(fake_segments, FakeTmp()),
    ):
        result = process_one_message(
            body,
            mock_job_store,
            mock_storage,
            "input-bucket",
        )

    assert result is True
    mock_job_store.update.assert_called()
    calls = mock_job_store.update.call_args_list
    assert any(
        c[1].get("status") == JobStatus.CHUNKING_IN_PROGRESS.value
        for c in calls
    )
    assert any(
        c[1].get("status") == JobStatus.CHUNKING_COMPLETE.value
        and c[1].get("total_segments") == 2
        for c in calls
    )
    assert mock_storage.upload.call_count == 2
    upload_calls = mock_storage.upload.call_args_list
    keys_uploaded = [c[0][1] for c in upload_calls]
    assert "input-bucket" in [c[0][0] for c in upload_calls]
    assert "segments/test-job/00000_00002_anaglyph.mp4" in keys_uploaded
    assert "segments/test-job/00001_00002_anaglyph.mp4" in keys_uploaded


def test_process_one_message_invalid_body_returns_false(
    mock_job_store: MagicMock,
    mock_storage: MagicMock,
) -> None:
    result = process_one_message(
        "not valid json",
        mock_job_store,
        mock_storage,
        "input-bucket",
    )
    assert result is False
    mock_job_store.update.assert_not_called()
    mock_storage.download.assert_not_called()


def test_process_one_message_job_not_found_returns_false(
    mock_storage: MagicMock,
) -> None:
    store = MagicMock()
    store.get.return_value = None
    body = _make_s3_event_body("input-bucket", "input/missing-job/source.mp4")
    result = process_one_message(body, store, mock_storage, "input-bucket")
    assert result is False
    store.update.assert_not_called()
    mock_storage.download.assert_not_called()
