"""Tests for inference queue consumer (process_one_message, run_loop)."""

from unittest.mock import MagicMock, patch

import pytest
from stereo_spot_shared import QueueMessage

from tests.helpers import make_s3_event_body
from video_worker.inference import (
    _max_in_flight,
    process_one_message,
    run_loop,
)


def test_process_one_message_mock_pipeline() -> None:
    """Mocked storage/segment_store: download, stub, upload, put completion."""
    storage = MagicMock()
    storage.download.return_value = b"fake segment bytes"
    segment_store = MagicMock()
    body = make_s3_event_body("input-bucket", "segments/job-xyz/00001_00005_sbs.mp4")
    result = process_one_message(body, storage, segment_store, "output-bucket")
    assert result is True
    storage.download.assert_called_once_with("input-bucket", "segments/job-xyz/00001_00005_sbs.mp4")
    storage.upload.assert_called_once()
    upload_args = storage.upload.call_args[0]
    assert upload_args[0] == "output-bucket"
    assert upload_args[1] == "jobs/job-xyz/segments/1.mp4"
    assert upload_args[2] == b"fake segment bytes"
    segment_store.put.assert_called_once()
    completion = segment_store.put.call_args[0][0]
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


def test_process_one_message_sagemaker_backend_raises() -> None:
    """SageMaker: process_one_message not used; run_loop with invocation_store required."""
    storage = MagicMock()
    segment_store = MagicMock()
    body = make_s3_event_body("input-bucket", "segments/job-xyz/00001_00005_sbs.mp4")
    env = {"INFERENCE_BACKEND": "sagemaker", "SAGEMAKER_ENDPOINT_NAME": "my-ep"}
    with patch.dict("os.environ", env):
        with pytest.raises(ValueError, match="event-driven completion"):
            process_one_message(body, storage, segment_store, "output-bucket")


def test_max_in_flight_default_and_clamp() -> None:
    """_max_in_flight returns env value clamped to 1–20."""
    with patch.dict("os.environ", {}, clear=False):
        if "INFERENCE_MAX_IN_FLIGHT" in __import__("os").environ:
            del __import__("os").environ["INFERENCE_MAX_IN_FLIGHT"]
        assert _max_in_flight() == 5
    with patch.dict("os.environ", {"INFERENCE_MAX_IN_FLIGHT": "10"}):
        assert _max_in_flight() == 10
    with patch.dict("os.environ", {"INFERENCE_MAX_IN_FLIGHT": "1"}):
        assert _max_in_flight() == 1
    with patch.dict("os.environ", {"INFERENCE_MAX_IN_FLIGHT": "25"}):
        assert _max_in_flight() == 20
    with patch.dict("os.environ", {"INFERENCE_MAX_IN_FLIGHT": "0"}):
        assert _max_in_flight() == 1
    with patch.dict("os.environ", {"INFERENCE_MAX_IN_FLIGHT": "x"}):
        assert _max_in_flight() == 5


def test_run_loop_sagemaker_fire_and_forget_put_and_delete() -> None:
    """SageMaker loop: one msg -> invoke_async, put store, delete; exit via sleep raise."""
    body = make_s3_event_body("input-bucket", "segments/job-xyz/00001_00005_sbs.mp4")
    msg = QueueMessage(receipt_handle="rh1", body=body)
    receiver = MagicMock()
    receiver.receive.side_effect = [[msg], []]  # first call one message, then empty
    segment_store = MagicMock()
    invocation_store = MagicMock()
    sagemaker_mock = MagicMock()

    with patch.dict(
        "os.environ",
        {
            "INFERENCE_BACKEND": "sagemaker",
            "SAGEMAKER_ENDPOINT_NAME": "ep",
            "SAGEMAKER_REGION": "us-east-1",
            "INFERENCE_MAX_IN_FLIGHT": "5",
        },
    ):
        with patch("boto3.client", return_value=sagemaker_mock):
            with patch(
                "video_worker.inference.invoke_sagemaker_async",
                return_value="s3://bucket/sagemaker-async-responses/xyz",
            ):
                with patch("video_worker.inference.time.sleep", side_effect=StopIteration):
                    try:
                        run_loop(
                            receiver,
                            MagicMock(),
                            segment_store,
                            "output-bucket",
                            invocation_store=invocation_store,
                            poll_interval_sec=1.0,
                        )
                    except StopIteration:
                        pass
    receiver.delete.assert_called_once_with("rh1")
    invocation_store.put.assert_called_once_with(
        "s3://bucket/sagemaker-async-responses/xyz",
        "job-xyz",
        1,
        5,
        "s3://output-bucket/jobs/job-xyz/segments/1.mp4",
    )
    segment_store.put.assert_not_called()
