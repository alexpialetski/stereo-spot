"""Tests for final output key building."""

from media_worker.output_key import build_final_key, build_reassembly_done_key


def test_build_final_key() -> None:
    assert build_final_key("job-abc") == "jobs/job-abc/final.mp4"
    assert build_final_key("xyz") == "jobs/xyz/final.mp4"


def test_build_reassembly_done_key() -> None:
    assert build_reassembly_done_key("job-abc") == "jobs/job-abc/.reassembly-done"
    assert build_reassembly_done_key("xyz") == "jobs/xyz/.reassembly-done"
