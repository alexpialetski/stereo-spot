"""Tests for output-events queue consumer (process_one_output_event_message). Backpressure only."""

from unittest.mock import MagicMock

from tests.helpers import make_s3_event_body
from video_worker.output_events import process_one_output_event_message


def test_segment_file_event_ack_only() -> None:
    """Segment file event (jobs/.../segments/*.mp4): return True, ack only."""
    body = make_s3_event_body("output-bucket", "jobs/job-abc/segments/3.mp4")
    result = process_one_output_event_message(body, "output-bucket")
    assert result is True


def test_final_mp4_event_ack_only() -> None:
    """final.mp4: return True, ack only (job-worker sets completed)."""
    body = make_s3_event_body("output-bucket", "jobs/job-abc/final.mp4")
    result = process_one_output_event_message(body, "output-bucket")
    assert result is True


def test_reassembly_done_event_ack_only() -> None:
    """.reassembly-done: return True, ack only (job-worker sets completed)."""
    body = make_s3_event_body("output-bucket", "jobs/job-abc/.reassembly-done")
    result = process_one_output_event_message(body, "output-bucket")
    assert result is True


def test_sagemaker_success_releases_semaphore() -> None:
    """SageMaker success: release semaphore, do not delete from store."""
    invocation_store = MagicMock()
    invocation_store.get.return_value = {
        "job_id": "job-xyz",
        "segment_index": 2,
        "total_segments": 4,
        "output_s3_uri": "s3://output-bucket/jobs/job-xyz/segments/2.mp4",
    }
    inference_semaphore = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/some-invocation-id")
    result = process_one_output_event_message(
        body,
        "output-bucket",
        invocation_store=invocation_store,
        inference_semaphore=inference_semaphore,
    )
    assert result is True
    inference_semaphore.release.assert_called_once()
    invocation_store.delete.assert_not_called()


def test_sagemaker_success_no_semaphore_ack_only() -> None:
    """SageMaker success when inference_semaphore is None: return True."""
    invocation_store = MagicMock()
    invocation_store.get.return_value = {"job_id": "j", "segment_index": 0}
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/xyz")
    result = process_one_output_event_message(
        body, "output-bucket", invocation_store=invocation_store
    )
    assert result is True
    invocation_store.delete.assert_not_called()


def test_sagemaker_success_no_store_still_releases_semaphore() -> None:
    """SageMaker success when invocation_store is None: still release semaphore if set."""
    inference_semaphore = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/xyz")
    result = process_one_output_event_message(
        body, "output-bucket", inference_semaphore=inference_semaphore
    )
    assert result is True
    inference_semaphore.release.assert_called_once()


def test_sagemaker_success_store_miss_releases_semaphore() -> None:
    """SageMaker success when store has no record: release semaphore (avoid slot leak)."""
    invocation_store = MagicMock()
    invocation_store.get.return_value = None
    inference_semaphore = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/unknown")
    result = process_one_output_event_message(
        body,
        "output-bucket",
        invocation_store=invocation_store,
        inference_semaphore=inference_semaphore,
    )
    assert result is True
    inference_semaphore.release.assert_called_once()
    invocation_store.delete.assert_not_called()


def test_sagemaker_failure_releases_semaphore() -> None:
    """SageMaker failure: release semaphore; do not delete (job-worker deletes)."""
    invocation_store = MagicMock()
    invocation_store.get.return_value = {
        "job_id": "job-fail",
        "segment_index": 0,
        "total_segments": 1,
        "output_s3_uri": "s3://out/jobs/job-fail/segments/0.mp4",
    }
    inference_semaphore = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-failures/fail-id")
    result = process_one_output_event_message(
        body,
        "output-bucket",
        invocation_store=invocation_store,
        inference_semaphore=inference_semaphore,
    )
    assert result is True
    inference_semaphore.release.assert_called_once()
    invocation_store.delete.assert_not_called()


def test_sagemaker_failure_no_record_releases_semaphore() -> None:
    """Failure event with no invocation record: release semaphore to avoid slot leak."""
    invocation_store = MagicMock()
    invocation_store.get.return_value = None
    inference_semaphore = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-failures/some-id-error.out")
    result = process_one_output_event_message(
        body,
        "output-bucket",
        invocation_store=invocation_store,
        inference_semaphore=inference_semaphore,
    )
    assert result is True
    inference_semaphore.release.assert_called_once()


def test_invalid_body_returns_true_delete_poison() -> None:
    """Invalid S3 event body: return True so caller deletes (avoid poison)."""
    result = process_one_output_event_message("not json", "output-bucket")
    assert result is True
