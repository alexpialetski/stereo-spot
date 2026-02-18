"""Tests for video worker pipeline with mocked storage and segment store."""

import json
from unittest.mock import MagicMock, patch

from stereo_spot_shared import Job, JobStatus, ReassemblyPayload, SegmentCompletion, StereoMode

from video_worker.runner import (
    maybe_trigger_reassembly,
    process_one_message,
    process_one_segment_output_message,
)


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
    """SageMaker backend: invokes endpoint only; completion written by segment-output consumer."""
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
    segment_store.put.assert_not_called()


def test_process_one_segment_output_message_valid_key_puts_completion() -> None:
    """Segment-output: valid jobs/{job_id}/segments/{i}.mp4 key -> put SegmentCompletion."""
    segment_store = MagicMock()
    body = _make_s3_event_body("output-bucket", "jobs/job-abc/segments/3.mp4")
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
    body = _make_s3_event_body("output-bucket", "jobs/job-abc/final.mp4")
    result = process_one_segment_output_message(body, segment_store, "output-bucket")
    assert result is False
    segment_store.put.assert_not_called()


def test_process_one_segment_output_message_invalid_body_returns_false() -> None:
    """Segment-output: invalid JSON -> return False, no put."""
    segment_store = MagicMock()
    result = process_one_segment_output_message("not json", segment_store, "output-bucket")
    assert result is False
    segment_store.put.assert_not_called()


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
    reassembly_sender.send.assert_called_once_with(ReassemblyPayload(job_id="job-1").model_dump_json())


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

    body = _make_s3_event_body("output-bucket", "jobs/job-last/segments/1.mp4")
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
    reassembly_sender.send.assert_called_once_with(ReassemblyPayload(job_id="job-last").model_dump_json())
