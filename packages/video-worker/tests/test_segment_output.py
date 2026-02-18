"""Tests for segment-output queue consumer (process_one_segment_output_message)."""

from unittest.mock import MagicMock

from stereo_spot_shared import Job, JobStatus, ReassemblyPayload, SegmentCompletion, StereoMode

from tests.helpers import make_s3_event_body
from video_worker.segment_output import process_one_segment_output_message


def test_process_one_segment_output_message_valid_key_puts_completion() -> None:
    """Segment-output: valid jobs/{job_id}/segments/{i}.mp4 key -> put SegmentCompletion."""
    segment_store = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-abc/segments/3.mp4")
    result = process_one_segment_output_message(body, segment_store, "output-bucket")
    assert result is True
    segment_store.put.assert_called_once()
    completion: SegmentCompletion = segment_store.put.call_args[0][0]
    assert completion.job_id == "job-abc"
    assert completion.segment_index == 3
    assert completion.output_s3_uri == "s3://output-bucket/jobs/job-abc/segments/3.mp4"
    assert completion.total_segments is None


def test_process_one_segment_output_message_final_mp4_returns_false() -> None:
    """Segment-output: final.mp4 key is not a segment -> return False, no put."""
    segment_store = MagicMock()
    body = make_s3_event_body("output-bucket", "jobs/job-abc/final.mp4")
    result = process_one_segment_output_message(body, segment_store, "output-bucket")
    assert result is False
    segment_store.put.assert_not_called()


def test_process_one_segment_output_message_invalid_body_returns_false() -> None:
    """Segment-output: invalid JSON -> return False, no put."""
    segment_store = MagicMock()
    result = process_one_segment_output_message("not json", segment_store, "output-bucket")
    assert result is False
    segment_store.put.assert_not_called()


def test_process_one_segment_output_message_with_reassembly_deps_triggers() -> None:
    """With reassembly deps and last segment, maybe_trigger_reassembly runs and send is called."""
    segment_store = MagicMock()
    segment_store.query_by_job.return_value = [
        SegmentCompletion(
            job_id="job-last", segment_index=0,
            output_s3_uri="s3://o/0.mp4", completed_at=1,
        ),
        SegmentCompletion(
            job_id="job-last", segment_index=1,
            output_s3_uri="s3://o/1.mp4", completed_at=2,
        ),
    ]
    job_store = MagicMock()
    job_store.get.return_value = Job(
        job_id="job-last",
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=2,
    )
    reassembly_triggered = MagicMock()
    reassembly_triggered.try_create_triggered.return_value = True
    reassembly_sender = MagicMock()

    body = make_s3_event_body("output-bucket", "jobs/job-last/segments/1.mp4")
    result = process_one_segment_output_message(
        body,
        segment_store,
        "output-bucket",
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
    )

    assert result is True
    segment_store.put.assert_called_once()
    reassembly_triggered.try_create_triggered.assert_called_once_with("job-last")
    reassembly_sender.send.assert_called_once_with(
        ReassemblyPayload(job_id="job-last").model_dump_json()
    )
