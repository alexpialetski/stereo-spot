"""Tests for output-events queue consumer (process_one_output_event_message)."""

from unittest.mock import MagicMock

from stereo_spot_shared import Job, JobStatus, ReassemblyPayload, SegmentCompletion, StereoMode

from tests.helpers import make_s3_event_body
from video_worker.output_events import process_one_output_event_message


def test_segment_file_event_no_completion() -> None:
    """Segment file event (jobs/.../segments/*.mp4): return True, do not put SegmentCompletion."""
    segment_store = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-abc/segments/3.mp4")
    result = process_one_output_event_message(body, segment_store, "output-bucket")
    assert result is True
    segment_store.put.assert_not_called()


def test_segment_file_final_mp4_ack_only() -> None:
    """Non-segment key (final.mp4) without job_store: return True, no put."""
    segment_store = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-abc/final.mp4")
    result = process_one_output_event_message(body, segment_store, "output-bucket")
    assert result is True
    segment_store.put.assert_not_called()


def test_final_mp4_event_with_job_store_sets_completed() -> None:
    """final.mp4 event with job_store: video-worker sets job completed."""
    segment_store = MagicMock()
    job_store = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-xyz/final.mp4")
    result = process_one_output_event_message(
        body, segment_store, "output-bucket", job_store=job_store
    )
    assert result is True
    segment_store.put.assert_not_called()
    job_store.update.assert_called_once()
    call_args = job_store.update.call_args
    assert call_args[0][0] == "job-xyz"
    assert call_args[1]["status"] == JobStatus.COMPLETED.value
    assert "completed_at" in call_args[1]


def test_reassembly_done_sentinel_event_sets_completed() -> None:
    """.reassembly-done sentinel event with job_store: video-worker sets job completed."""
    segment_store = MagicMock()
    job_store = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-abc/.reassembly-done")
    result = process_one_output_event_message(
        body, segment_store, "output-bucket", job_store=job_store
    )
    assert result is True
    segment_store.put.assert_not_called()
    job_store.update.assert_called_once()
    call_args = job_store.update.call_args
    assert call_args[0][0] == "job-abc"
    assert call_args[1]["status"] == JobStatus.COMPLETED.value
    assert "completed_at" in call_args[1]


def test_sagemaker_success_event_puts_completion_and_deletes_from_store() -> None:
    """SageMaker success: lookup, put SegmentCompletion, trigger reassembly, delete from store."""
    segment_store = MagicMock()
    # After put, query_by_job returns 4 completions so reassembly triggers
    segment_store.query_by_job.return_value = [
        SegmentCompletion(
            job_id="job-xyz",
            segment_index=i,
            output_s3_uri=f"s3://o/{i}.mp4",
            completed_at=1,
        )
        for i in range(4)
    ]
    invocation_store = MagicMock()
    invocation_store.get.return_value = {
        "job_id": "job-xyz",
        "segment_index": 2,
        "total_segments": 4,
        "output_s3_uri": "s3://output-bucket/jobs/job-xyz/segments/2.mp4",
    }
    job_store = MagicMock()
    job_store.get.return_value = Job(
        job_id="job-xyz",
        mode=StereoMode.SBS,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=4,
    )
    reassembly_triggered = MagicMock()
    reassembly_triggered.try_create_triggered.return_value = True
    reassembly_sender = MagicMock()

    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/some-invocation-id")
    result = process_one_output_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
        invocation_store=invocation_store,
    )

    assert result is True
    s3_uri = "s3://output-bucket/sagemaker-async-responses/some-invocation-id"
    invocation_store.get.assert_called_once_with(s3_uri)
    segment_store.put.assert_called_once()
    completion: SegmentCompletion = segment_store.put.call_args[0][0]
    assert completion.job_id == "job-xyz"
    assert completion.segment_index == 2
    assert completion.total_segments == 4
    assert completion.output_s3_uri == "s3://output-bucket/jobs/job-xyz/segments/2.mp4"
    invocation_store.delete.assert_called_once_with(s3_uri)
    reassembly_triggered.try_create_triggered.assert_called_once_with("job-xyz")
    reassembly_sender.send.assert_called_once_with(
        ReassemblyPayload(job_id="job-xyz").model_dump_json()
    )


def test_sagemaker_success_event_no_store_idempotent_delete() -> None:
    """SageMaker success event when invocation_store is None: return True, no put."""
    segment_store = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/xyz")
    result = process_one_output_event_message(
        body, segment_store, "output-bucket", invocation_store=None
    )
    assert result is True
    segment_store.put.assert_not_called()


def test_sagemaker_success_event_store_miss_idempotent_delete() -> None:
    """SageMaker success event when store has no record: return True, no put (idempotent)."""
    segment_store = MagicMock()
    invocation_store = MagicMock()
    invocation_store.get.return_value = None
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/unknown")
    result = process_one_output_event_message(
        body, segment_store, "output-bucket", invocation_store=invocation_store
    )
    assert result is True
    segment_store.put.assert_not_called()
    invocation_store.delete.assert_not_called()


def test_sagemaker_failure_event_deletes_from_store_optional_mark_failed() -> None:
    """SageMaker failure event: delete from store, optionally mark job failed."""
    segment_store = MagicMock()
    invocation_store = MagicMock()
    invocation_store.get.return_value = {
        "job_id": "job-fail",
        "segment_index": 0,
        "total_segments": 1,
        "output_s3_uri": "s3://out/jobs/job-fail/segments/0.mp4",
    }
    job_store = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-failures/fail-id")
    result = process_one_output_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        invocation_store=invocation_store,
    )
    assert result is True
    segment_store.put.assert_not_called()
    job_store.update.assert_called_once_with("job-fail", status="failed")
    invocation_store.delete.assert_called_once_with(
        "s3://output-bucket/sagemaker-async-failures/fail-id"
    )


def test_sagemaker_failure_event_no_record_releases_semaphore() -> None:
    """Failure event with no invocation record: release semaphore to avoid slot leak."""
    segment_store = MagicMock()
    invocation_store = MagicMock()
    invocation_store.get.return_value = None  # store keyed by success URI, not failure
    inference_semaphore = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-failures/some-id-error.out")
    result = process_one_output_event_message(
        body,
        segment_store,
        "output-bucket",
        invocation_store=invocation_store,
        inference_semaphore=inference_semaphore,
    )
    assert result is True
    segment_store.put.assert_not_called()
    inference_semaphore.release.assert_called_once()


def test_invalid_body_returns_true_delete_poison() -> None:
    """Invalid S3 event body: return True so caller deletes (avoid poison)."""
    segment_store = MagicMock()
    result = process_one_output_event_message("not json", segment_store, "output-bucket")
    assert result is True
    segment_store.put.assert_not_called()
