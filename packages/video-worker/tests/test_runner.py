"""Tests for video worker pipeline with mocked storage and segment store."""

import json
from unittest.mock import MagicMock, patch

from stereo_spot_shared import SegmentCompletion

from video_worker.runner import process_one_message


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


def test_process_one_message_mock_pipeline() -> None:
    """Mocked storage/segment_store: download, stub, upload, put completion."""
    storage = MagicMock()
    storage.download.return_value = b"fake segment bytes"
    segment_store = MagicMock()

    body = _make_s3_event_body(
        "input-bucket",
        "segments/job-xyz/00001_00005_sbs.mp4",
    )
    result = process_one_message(
        body,
        storage,
        segment_store,
        "output-bucket",
    )

    assert result is True
    storage.download.assert_called_once_with("input-bucket", "segments/job-xyz/00001_00005_sbs.mp4")
    storage.upload.assert_called_once()
    upload_args = storage.upload.call_args[0]
    assert upload_args[0] == "output-bucket"
    assert upload_args[1] == "jobs/job-xyz/segments/1.mp4"
    assert upload_args[2] == b"fake segment bytes"

    segment_store.put.assert_called_once()
    completion: SegmentCompletion = segment_store.put.call_args[0][0]
    assert completion.job_id == "job-xyz"
    assert completion.segment_index == 1
    assert completion.output_s3_uri == "s3://output-bucket/jobs/job-xyz/segments/1.mp4"
    assert completion.total_segments == 5


def test_process_one_message_invalid_body_returns_false() -> None:
    storage = MagicMock()
    segment_store = MagicMock()
    result = process_one_message("not json", storage, segment_store, "output-bucket")
    assert result is False
    storage.download.assert_not_called()
    segment_store.put.assert_not_called()


def test_process_one_message_sagemaker_backend_no_download_upload() -> None:
    """Sagemaker backend: invokes endpoint and puts completion only (no download/upload)."""
    storage = MagicMock()
    segment_store = MagicMock()
    body = _make_s3_event_body(
        "input-bucket",
        "segments/job-xyz/00001_00005_sbs.mp4",
    )
    env = {"INFERENCE_BACKEND": "sagemaker", "SAGEMAKER_ENDPOINT_NAME": "my-ep"}
    with patch.dict("os.environ", env):
        with patch("video_worker.runner.invoke_sagemaker_endpoint") as mock_invoke:
            result = process_one_message(
                body,
                storage,
                segment_store,
                "output-bucket",
            )
    assert result is True
    storage.download.assert_not_called()
    storage.upload.assert_not_called()
    mock_invoke.assert_called_once_with(
        "s3://input-bucket/segments/job-xyz/00001_00005_sbs.mp4",
        "s3://output-bucket/jobs/job-xyz/segments/1.mp4",
        "my-ep",
        mode="sbs",
        region_name=None,
    )
    segment_store.put.assert_called_once()
    completion: SegmentCompletion = segment_store.put.call_args[0][0]
    assert completion.job_id == "job-xyz"
    assert completion.segment_index == 1
    assert completion.output_s3_uri == "s3://output-bucket/jobs/job-xyz/segments/1.mp4"
