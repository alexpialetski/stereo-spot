"""Tests for segment key generation (shared-types build_segment_key used by chunking)."""

from stereo_spot_shared import StereoMode, build_segment_key


def test_build_segment_key_anaglyph() -> None:
    key = build_segment_key(
        job_id="job-123",
        segment_index=0,
        total_segments=10,
        mode=StereoMode.ANAGLYPH,
    )
    assert key == "segments/job-123/00000_00010_anaglyph.mp4"


def test_build_segment_key_sbs() -> None:
    key = build_segment_key(
        job_id="abc",
        segment_index=42,
        total_segments=100,
        mode=StereoMode.SBS,
    )
    assert key == "segments/abc/00042_00100_sbs.mp4"


def test_build_segment_key_single_segment() -> None:
    key = build_segment_key(
        job_id="single",
        segment_index=0,
        total_segments=1,
        mode=StereoMode.ANAGLYPH,
    )
    assert key == "segments/single/00000_00001_anaglyph.mp4"
