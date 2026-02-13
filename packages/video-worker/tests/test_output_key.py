"""Tests for output segment key generation."""

from video_worker.output_key import build_output_segment_key


def test_build_output_segment_key() -> None:
    assert build_output_segment_key("job-123", 0) == "jobs/job-123/segments/0.mp4"
    assert build_output_segment_key("job-abc", 42) == "jobs/job-abc/segments/42.mp4"
