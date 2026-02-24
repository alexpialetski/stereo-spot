"""Tests for reassembly runner: lock behaviour, idempotency when final exists."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from stereo_spot_shared import Job, JobStatus, SegmentCompletion, StereoMode

from media_worker.reassembly import process_one_reassembly_message


def _make_message(job_id: str) -> str:
    return json.dumps({"job_id": job_id})


@pytest.fixture
def mock_job_store() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_segment_store() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_storage() -> MagicMock:
    s = MagicMock()
    s.exists.return_value = False
    s.download.return_value = b"fake"
    s.upload_file.return_value = None
    s.upload.return_value = None
    return s


@pytest.fixture
def mock_lock() -> MagicMock:
    return MagicMock()


def test_process_one_reassembly_message_invalid_body_returns_false(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """Invalid JSON or missing job_id yields False (do not delete message)."""
    result = process_one_reassembly_message(
        "not json",
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is False
    mock_lock.try_acquire.assert_not_called()


def test_process_one_reassembly_message_lock_not_acquired_returns_true(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When try_acquire returns False, we return True so the message is deleted (idempotent)."""
    mock_lock.try_acquire.return_value = False
    result = process_one_reassembly_message(
        _make_message("job-1"),
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is True
    mock_lock.try_acquire.assert_called_once_with("job-1")
    mock_job_store.get.assert_not_called()


def test_process_one_reassembly_message_idempotency_when_final_exists(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When final.mp4 exists, write .reassembly-done sentinel; video-worker sets completed."""
    mock_lock.try_acquire.return_value = True
    mock_job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=2,
    )
    # final exists, sentinel does not -> upload sentinel
    mock_storage.exists.side_effect = lambda b, k: k == "jobs/job-1/final.mp4"
    result = process_one_reassembly_message(
        _make_message("job-1"),
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is True
    mock_job_store.update.assert_not_called()
    mock_storage.upload.assert_called_once_with(
        "output-bucket", "jobs/job-1/.reassembly-done", b""
    )
    mock_segment_store.query_by_job.assert_not_called()
    mock_storage.upload_file.assert_not_called()


def test_process_one_reassembly_message_idempotency_when_final_and_sentinel_exist(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When final.mp4 and .reassembly-done already exist, return True without uploading."""
    mock_lock.try_acquire.return_value = True
    mock_job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=2,
    )
    mock_storage.exists.return_value = True  # both final and sentinel exist
    result = process_one_reassembly_message(
        _make_message("job-1"),
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is True
    mock_job_store.update.assert_not_called()
    mock_storage.upload.assert_not_called()
    mock_storage.upload_file.assert_not_called()


def test_process_one_reassembly_message_already_completed_returns_true(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When job status is already completed, return True (delete message)."""
    mock_lock.try_acquire.return_value = True
    mock_job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.SBS,
        status=JobStatus.COMPLETED,
        completed_at=9999,
    )
    result = process_one_reassembly_message(
        _make_message("job-1"),
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is True
    mock_job_store.update.assert_not_called()
    mock_storage.exists.assert_not_called()


def test_process_one_reassembly_message_job_not_found_returns_false(
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When job is missing, return False (retry)."""
    job_store = MagicMock()
    job_store.get.return_value = None
    mock_lock.try_acquire.return_value = True
    result = process_one_reassembly_message(
        _make_message("job-1"),
        job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is False


def test_process_one_reassembly_message_mock_pipeline(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
    tmp_path: Path,
) -> None:
    """Full flow with mocked concat: lock acquired, completions present, concat and upload."""
    mock_lock.try_acquire.return_value = True
    mock_job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=2,
    )
    mock_storage.exists.return_value = False
    mock_segment_store.query_by_job.return_value = [
        SegmentCompletion(
            job_id="job-1",
            segment_index=0,
            output_s3_uri="s3://out/jobs/job-1/segments/0.mp4",
            completed_at=1000,
        ),
        SegmentCompletion(
            job_id="job-1",
            segment_index=1,
            output_s3_uri="s3://out/jobs/job-1/segments/1.mp4",
            completed_at=1001,
        ),
    ]

    with patch(
        "media_worker.reassembly.build_concat_list_paths",
        return_value=[tmp_path / "0.mp4", tmp_path / "1.mp4"],
    ), patch(
        "media_worker.reassembly.concat_segments_to_file",
        side_effect=lambda paths, out: Path(out).write_bytes(b"concatenated"),
    ):
        result = process_one_reassembly_message(
            _make_message("job-1"),
            mock_job_store,
            mock_segment_store,
            mock_storage,
            mock_lock,
            "output-bucket",
        )
    assert result is True
    mock_job_store.update.assert_not_called()  # video-worker sets completed on final.mp4 event
    mock_storage.upload_file.assert_called_once()
    assert mock_storage.upload_file.call_args[0][1] == "jobs/job-1/final.mp4"
