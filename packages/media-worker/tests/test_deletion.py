"""Tests for deletion runner: parse body, delete S3 and DynamoDB."""

import json
from unittest.mock import MagicMock

import pytest
from stereo_spot_shared import Job, JobStatus, StereoMode

from media_worker.deletion import process_one_deletion_message


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
    s.list_object_keys.return_value = []
    return s


@pytest.fixture
def mock_lock() -> MagicMock:
    return MagicMock()


def test_process_one_deletion_message_invalid_body_returns_false(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """Invalid JSON or missing job_id yields False (do not delete message)."""
    result = process_one_deletion_message(
        "not json",
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "input-bucket",
        "output-bucket",
    )
    assert result is False
    mock_segment_store.delete_by_job.assert_not_called()
    mock_lock.delete.assert_not_called()


def test_process_one_deletion_message_valid_body_deletes_artifacts(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """Valid body: job deleted; storage delete/list, segment_store.delete_by_job, lock.delete."""
    job_id = "job-1"
    mock_job_store.get.return_value = Job(
        job_id=job_id,
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.DELETED,
    )
    mock_storage.list_object_keys.return_value = []

    result = process_one_deletion_message(
        _make_message(job_id),
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "input-bucket",
        "output-bucket",
    )
    assert result is True
    mock_job_store.get.assert_called_once_with(job_id)
    mock_storage.delete.assert_any_call("input-bucket", f"input/{job_id}/source.mp4")
    mock_storage.list_object_keys.assert_any_call("input-bucket", f"segments/{job_id}/")
    mock_storage.list_object_keys.assert_any_call("output-bucket", f"jobs/{job_id}/")
    mock_segment_store.delete_by_job.assert_called_once_with(job_id)
    mock_lock.delete.assert_called_once_with(job_id)


def test_process_one_deletion_message_skips_cleanup_when_job_not_deleted(
    mock_job_store: MagicMock,
    mock_segment_store: MagicMock,
    mock_storage: MagicMock,
    mock_lock: MagicMock,
) -> None:
    """When job exists and status is not deleted, return True but skip S3/DynamoDB cleanup."""
    job_id = "job-2"
    mock_job_store.get.return_value = Job(
        job_id=job_id,
        mode=StereoMode.SBS,
        status=JobStatus.COMPLETED,
        completed_at=1000,
    )

    result = process_one_deletion_message(
        _make_message(job_id),
        mock_job_store,
        mock_segment_store,
        mock_storage,
        mock_lock,
        "input-bucket",
        "output-bucket",
    )
    assert result is True
    mock_storage.delete.assert_not_called()
    mock_segment_store.delete_by_job.assert_not_called()
    mock_lock.delete.assert_not_called()
