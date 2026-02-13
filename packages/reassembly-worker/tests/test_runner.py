"""Tests for reassembly runner: lock behaviour, idempotency when final exists."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from stereo_spot_shared import Job, JobStatus, SegmentCompletion, StereoMode

from reassembly_worker.runner import process_one_message


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
    return s


@pytest.fixture
def mock_lock() -> MagicMock:
    return MagicMock()


def test_process_one_message_invalid_body_returns_false(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """Invalid JSON or missing job_id yields False (do not delete message)."""
    result = process_one_message(
        "not json",
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is False
    mock_lock.try_acquire.assert_not_called()


def test_process_one_message_lock_not_acquired_returns_true(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When try_acquire returns False, we return True so the message is deleted (idempotent)."""
    mock_lock.try_acquire.return_value = False
    result = process_one_message(
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


def test_process_one_message_idempotency_when_final_exists(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When final.mp4 already exists, update Job to completed and return True."""
    mock_lock.try_acquire.return_value = True
    mock_job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=2,
    )
    mock_storage.exists.return_value = True  # final already present
    result = process_one_message(
        _make_message("job-1"),
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is True
    mock_job_store.update.assert_called_once()
    call_kw = mock_job_store.update.call_args[1]
    assert call_kw["status"] == JobStatus.COMPLETED.value
    assert "completed_at" in call_kw
    mock_segment_store.query_by_job.assert_not_called()
    mock_storage.upload_file.assert_not_called()


def test_process_one_message_already_completed_returns_true(
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
    result = process_one_message(
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


def test_process_one_message_job_not_found_returns_false(
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When job is missing, return False (retry)."""
    job_store = MagicMock()
    job_store.get.return_value = None
    mock_lock.try_acquire.return_value = True
    result = process_one_message(
        _make_message("job-1"),
        job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "output-bucket",
    )
    assert result is False


def test_process_one_message_mock_pipeline(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
    tmp_path,
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
    def fake_concat(paths: list, out: Path) -> None:
        Path(out).write_bytes(b"concatenated")

    with patch(
        "reassembly_worker.runner.build_concat_list_paths",
        return_value=[tmp_path / "0.mp4", tmp_path / "1.mp4"],
    ), patch(
        "reassembly_worker.runner.concat_segments_to_file",
        side_effect=fake_concat,
    ):
        result = process_one_message(
            _make_message("job-1"),
            mock_job_store,
            mock_segment_store,
            mock_storage,
            mock_lock,
            "output-bucket",
        )
    assert result is True
    mock_job_store.update.assert_called_once()
    assert mock_job_store.update.call_args[1]["status"] == JobStatus.COMPLETED.value
    mock_storage.upload_file.assert_called_once()
    assert mock_storage.upload_file.call_args[0][1] == "jobs/job-1/final.mp4"
