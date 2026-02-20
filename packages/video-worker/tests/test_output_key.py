"""Tests for output segment key generation."""

from video_worker.output_key import (
    build_output_segment_key,
    build_output_segment_uri,
)


def test_build_output_segment_key() -> None:
    assert build_output_segment_key("job-123", 0) == "jobs/job-123/segments/0.mp4"
    assert build_output_segment_key("job-abc", 42) == "jobs/job-abc/segments/42.mp4"


def test_build_output_segment_uri() -> None:
    assert build_output_segment_uri("out-bucket", "job-1", 0) == (
        "s3://out-bucket/jobs/job-1/segments/0.mp4"
    )
    assert build_output_segment_uri("my-bucket", "jid", 3) == (
        "s3://my-bucket/jobs/jid/segments/3.mp4"
    )
