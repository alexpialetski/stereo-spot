"""Tests for job-status-events consumer (process_one_job_status_event_message)."""

from unittest.mock import MagicMock

from stereo_spot_shared import Job, JobStatus, ReassemblyPayload, SegmentCompletion, StereoMode

from job_worker.job_status_events import process_one_job_status_event_message

from .helpers import make_s3_event_body


def test_final_mp4_event_sets_completed() -> None:
    """final.mp4 event: job-worker sets job completed."""
    segment_store = MagicMock()
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-xyz/final.mp4")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
    )
    assert result is True
    segment_store.put.assert_not_called()
    job_store.update.assert_called_once()
    call_args = job_store.update.call_args
    assert call_args[0][0] == "job-xyz"
    assert call_args[1]["status"] == JobStatus.COMPLETED.value
    assert "completed_at" in call_args[1]


def test_reassembly_done_sentinel_sets_completed() -> None:
    """.reassembly-done sentinel event: job-worker sets job completed."""
    segment_store = MagicMock()
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-abc/.reassembly-done")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
    )
    assert result is True
    segment_store.put.assert_not_called()
    job_store.update.assert_called_once()
    call_args = job_store.update.call_args
    assert call_args[0][0] == "job-abc"
    assert call_args[1]["status"] == JobStatus.COMPLETED.value


def test_segment_file_event_puts_completion_and_triggers_reassembly() -> None:
    """Segment file (stub/HTTP path): write SegmentCompletion and maybe_trigger_reassembly."""
    segment_store = MagicMock()
    # After put, query_by_job sees 1 completion; return 1 to satisfy total_segments=1
    segment_store.query_by_job.return_value = [
        SegmentCompletion(
            job_id="job-abc",
            segment_index=0,
            output_s3_uri="s3://output-bucket/jobs/job-abc/segments/0.mp4",
            completed_at=1,
            total_segments=1,
        )
    ]
    job_store = MagicMock()
    job_store.get.return_value = Job(
        job_id="job-abc",
        mode=StereoMode.SBS,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=1,
    )
    reassembly_triggered = MagicMock()
    reassembly_triggered.try_create_triggered.return_value = True
    reassembly_sender = MagicMock()

    body = make_s3_event_body("output-bucket", "jobs/job-abc/segments/0.mp4")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
    )
    assert result is True
    segment_store.put.assert_called_once()
    completion: SegmentCompletion = segment_store.put.call_args[0][0]
    assert completion.job_id == "job-abc"
    assert completion.segment_index == 0
    assert completion.total_segments == 1
    assert completion.output_s3_uri == "s3://output-bucket/jobs/job-abc/segments/0.mp4"
    reassembly_triggered.try_create_triggered.assert_called_once_with("job-abc")
    reassembly_sender.send.assert_called_once_with(
        ReassemblyPayload(job_id="job-abc").model_dump_json()
    )


def test_segment_file_event_job_not_found_skips_completion() -> None:
    """Segment file when job not found: no put, no trigger."""
    segment_store = MagicMock()
    job_store = MagicMock()
    job_store.get.return_value = None
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-xyz/segments/0.mp4")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
    )
    assert result is True
    segment_store.put.assert_not_called()
    reassembly_sender.send.assert_not_called()


def test_sagemaker_success_puts_completion_deletes_store_triggers_reassembly() -> None:
    """SageMaker success: put SegmentCompletion, delete from store, trigger reassembly."""
    segment_store = MagicMock()
    segment_store.query_by_job.return_value = [
        SegmentCompletion(
            job_id="job-xyz",
            segment_index=i,
            output_s3_uri=f"s3://o/{i}.mp4",
            completed_at=1,
            total_segments=4,
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
    result = process_one_job_status_event_message(
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
    completion = segment_store.put.call_args[0][0]
    assert completion.job_id == "job-xyz"
    assert completion.segment_index == 2
    assert completion.total_segments == 4
    invocation_store.delete.assert_called_once_with(s3_uri)
    reassembly_sender.send.assert_called_once_with(
        ReassemblyPayload(job_id="job-xyz").model_dump_json()
    )


def test_sagemaker_success_no_invocation_store_skips() -> None:
    """SageMaker success when invocation_store is None: return True, no put."""
    segment_store = MagicMock()
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/xyz")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
        invocation_store=None,
    )
    assert result is True
    segment_store.put.assert_not_called()


def test_sagemaker_success_store_miss_idempotent_delete() -> None:
    """SageMaker success when store has no record: return True (idempotent)."""
    segment_store = MagicMock()
    invocation_store = MagicMock()
    invocation_store.get.return_value = None
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/unknown")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
        invocation_store=invocation_store,
    )
    assert result is True
    segment_store.put.assert_not_called()
    invocation_store.delete.assert_not_called()


def test_sagemaker_success_stream_record_delete_only() -> None:
    """Stream SageMaker success: delete from store only, no SegmentCompletion."""
    segment_store = MagicMock()
    invocation_store = MagicMock()
    invocation_store.get.return_value = {
        "job_id": "__stream__",
        "session_id": "session-abc",
        "segment_index": 42,
        "total_segments": 0,
        "output_s3_uri": "s3://output-bucket/stream_output/session-abc/seg_00042.mp4",
    }
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-responses/stream-response-id")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
        invocation_store=invocation_store,
    )
    assert result is True
    segment_store.put.assert_not_called()
    job_store.update.assert_not_called()
    reassembly_sender.send.assert_not_called()
    invocation_store.delete.assert_called_once_with(
        "s3://output-bucket/sagemaker-async-responses/stream-response-id"
    )


def test_sagemaker_failure_marks_failed_deletes_from_store() -> None:
    """SageMaker failure: mark job failed, delete from store."""
    segment_store = MagicMock()
    invocation_store = MagicMock()
    invocation_store.get.return_value = {
        "job_id": "job-fail",
        "segment_index": 0,
        "total_segments": 1,
        "output_s3_uri": "s3://out/jobs/job-fail/segments/0.mp4",
    }
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-failures/fail-id")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
        invocation_store=invocation_store,
    )
    assert result is True
    segment_store.put.assert_not_called()
    job_store.update.assert_called_once_with("job-fail", status=JobStatus.FAILED.value)
    invocation_store.delete.assert_called_once_with(
        "s3://output-bucket/sagemaker-async-failures/fail-id"
    )


def test_sagemaker_failure_stream_record_delete_only() -> None:
    """SageMaker failure for stream: delete from store only, do not mark job failed."""
    segment_store = MagicMock()
    invocation_store = MagicMock()
    invocation_store.get.return_value = {
        "job_id": "__stream__",
        "session_id": "session-xyz",
        "segment_index": 1,
        "output_s3_uri": "s3://output-bucket/stream_output/session-xyz/seg_00001.mp4",
    }
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-failures/stream-fail-id")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
        invocation_store=invocation_store,
    )
    assert result is True
    job_store.update.assert_not_called()
    invocation_store.delete.assert_called_once()


def test_sagemaker_failure_no_record_idempotent_delete() -> None:
    """SageMaker failure when store has no record: return True (idempotent)."""
    segment_store = MagicMock()
    invocation_store = MagicMock()
    invocation_store.get.return_value = None
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    body = make_s3_event_body("output-bucket", "sagemaker-async-failures/some-id-error.out")
    result = process_one_job_status_event_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
        invocation_store=invocation_store,
    )
    assert result is True
    segment_store.put.assert_not_called()
    job_store.update.assert_not_called()
    invocation_store.delete.assert_not_called()


def test_invalid_body_returns_true_delete_poison() -> None:
    """Invalid S3 event body: return True so caller deletes (avoid poison)."""
    segment_store = MagicMock()
    job_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()
    result = process_one_job_status_event_message(
        "not json",
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
    )
    assert result is True
    segment_store.put.assert_not_called()
