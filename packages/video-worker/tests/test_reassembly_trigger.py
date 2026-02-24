"""Tests for reassembly trigger (maybe_trigger_reassembly)."""

from unittest.mock import MagicMock

from stereo_spot_shared import Job, JobStatus, ReassemblyPayload, SegmentCompletion, StereoMode

from video_worker.reassembly_trigger import maybe_trigger_reassembly


def test_maybe_trigger_reassembly_sends_when_last_segment() -> None:
    """When job is chunking_complete and count == total_segments, conditional create and send."""
    job_store = MagicMock()
    job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.SBS,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=2,
    )
    segment_store = MagicMock()
    segment_store.query_by_job.return_value = [
        SegmentCompletion(
            job_id="job-1", segment_index=0,
            output_s3_uri="s3://o/jobs/job-1/segments/0.mp4", completed_at=1,
        ),
        SegmentCompletion(
            job_id="job-1", segment_index=1,
            output_s3_uri="s3://o/jobs/job-1/segments/1.mp4", completed_at=2,
        ),
    ]
    reassembly_triggered = MagicMock()
    reassembly_triggered.try_create_triggered.return_value = True
    reassembly_sender = MagicMock()

    maybe_trigger_reassembly(
        "job-1",
        job_store,
        segment_store,
        reassembly_triggered,
        reassembly_sender,
    )

    reassembly_triggered.try_create_triggered.assert_called_once_with("job-1")
    reassembly_sender.send.assert_called_once_with(
        ReassemblyPayload(job_id="job-1").model_dump_json()
    )
    job_store.update.assert_called_once_with("job-1", status=JobStatus.REASSEMBLING.value)


def test_maybe_trigger_reassembly_skips_when_not_chunking_complete() -> None:
    """When job status is not chunking_complete, do not send."""
    job_store = MagicMock()
    job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.SBS,
        status=JobStatus.CHUNKING_IN_PROGRESS,
        total_segments=2,
    )
    segment_store = MagicMock()
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()

    maybe_trigger_reassembly(
        "job-1",
        job_store,
        segment_store,
        reassembly_triggered,
        reassembly_sender,
    )

    segment_store.query_by_job.assert_not_called()
    reassembly_triggered.try_create_triggered.assert_not_called()
    reassembly_sender.send.assert_not_called()


def test_maybe_trigger_reassembly_skips_when_count_ne_total_segments() -> None:
    """When count != total_segments, do not send."""
    job_store = MagicMock()
    job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.SBS,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=3,
    )
    segment_store = MagicMock()
    segment_store.query_by_job.return_value = [
        SegmentCompletion(
            job_id="job-1", segment_index=0,
            output_s3_uri="s3://o/0.mp4", completed_at=1,
        ),
    ]
    reassembly_triggered = MagicMock()
    reassembly_sender = MagicMock()

    maybe_trigger_reassembly(
        "job-1",
        job_store,
        segment_store,
        reassembly_triggered,
        reassembly_sender,
    )

    reassembly_triggered.try_create_triggered.assert_not_called()
    reassembly_sender.send.assert_not_called()


def test_maybe_trigger_reassembly_skips_when_already_triggered() -> None:
    """When try_create_triggered returns False (already exists), do not send."""
    job_store = MagicMock()
    job_store.get.return_value = Job(
        job_id="job-1",
        mode=StereoMode.SBS,
        status=JobStatus.CHUNKING_COMPLETE,
        total_segments=1,
    )
    segment_store = MagicMock()
    segment_store.query_by_job.return_value = [
        SegmentCompletion(
            job_id="job-1", segment_index=0,
            output_s3_uri="s3://o/0.mp4", completed_at=1,
        ),
    ]
    reassembly_triggered = MagicMock()
    reassembly_triggered.try_create_triggered.return_value = False
    reassembly_sender = MagicMock()

    maybe_trigger_reassembly(
        "job-1",
        job_store,
        segment_store,
        reassembly_triggered,
        reassembly_sender,
    )

    reassembly_triggered.try_create_triggered.assert_called_once_with("job-1")
    reassembly_sender.send.assert_not_called()
