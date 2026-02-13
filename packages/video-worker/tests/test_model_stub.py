"""Tests for stub model (copy pass-through)."""

from video_worker.model_stub import process_segment


def test_process_segment_returns_unchanged() -> None:
    data = b"fake video segment bytes"
    assert process_segment(data) is data
