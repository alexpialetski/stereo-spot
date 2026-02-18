"""Tests for segment and input key parsers."""

from stereo_spot_shared import (
    StereoMode,
    build_segment_key,
    parse_input_key,
    parse_output_segment_key,
    parse_segment_key,
)


class TestSegmentKeyRoundTrip:
    """Segment key build and parse round-trip."""

    def test_round_trip_anaglyph(self) -> None:
        bucket = "my-bucket"
        job_id = "job-abc"
        segment_index = 42
        total_segments = 100
        mode = StereoMode.ANAGLYPH
        key = build_segment_key(job_id, segment_index, total_segments, mode)
        assert key == "segments/job-abc/00042_00100_anaglyph.mp4"
        payload = parse_segment_key(bucket, key)
        assert payload is not None
        assert payload.job_id == job_id
        assert payload.segment_index == segment_index
        assert payload.total_segments == total_segments
        assert payload.mode == mode
        assert payload.segment_s3_uri == f"s3://{bucket}/{key}"

    def test_round_trip_sbs(self) -> None:
        bucket = "input-bucket"
        job_id = "xyz-123"
        key = build_segment_key(
            job_id, segment_index=0, total_segments=1, mode=StereoMode.SBS
        )
        assert key == "segments/xyz-123/00000_00001_sbs.mp4"
        payload = parse_segment_key(bucket, key)
        assert payload is not None
        assert payload.job_id == job_id
        assert payload.segment_index == 0
        assert payload.total_segments == 1
        assert payload.mode == StereoMode.SBS


class TestInvalidSegmentKey:
    """Invalid segment keys are rejected (return None)."""

    def test_wrong_prefix_returns_none(self) -> None:
        assert parse_segment_key("b", "input/job/source.mp4") is None

    def test_no_slash_after_prefix_returns_none(self) -> None:
        assert parse_segment_key("b", "segments/noslash") is None

    def test_bad_filename_format_returns_none(self) -> None:
        assert parse_segment_key("b", "segments/job/0_1_anaglyph.mp4") is None

    def test_invalid_mode_returns_none(self) -> None:
        assert parse_segment_key("b", "segments/job/00000_00001_foo.mp4") is None

    def test_segment_index_ge_total_returns_none(self) -> None:
        assert (
            parse_segment_key("b", "segments/job/00001_00001_anaglyph.mp4") is None
        )

    def test_empty_job_id_returns_none(self) -> None:
        assert parse_segment_key("b", "segments//00000_00001_anaglyph.mp4") is None


class TestInputKeyParser:
    """Input key parser: input/{job_id}/source.mp4 -> job_id."""

    def test_valid_input_key(self) -> None:
        assert parse_input_key("input/job-abc/source.mp4") == "job-abc"
        assert parse_input_key("input/xyz-123/source.mp4") == "xyz-123"

    def test_invalid_input_key_returns_none(self) -> None:
        assert parse_input_key("input/job-abc/source.mp4 ") is None
        assert parse_input_key(" input/job-abc/source.mp4") is None
        assert parse_input_key("output/job-abc/source.mp4") is None
        assert parse_input_key("input/job-abc/other.mp4") is None
        assert parse_input_key("input//source.mp4") is None
        assert parse_input_key("input/source.mp4") is None
        assert parse_input_key("input/job-abc/source.mp4/extra") is None


class TestOutputSegmentKeyParser:
    """Parse jobs/{job_id}/segments/{segment_index}.mp4 -> (job_id, segment_index)."""

    def test_valid_output_segment_key(self) -> None:
        assert parse_output_segment_key("out-bucket", "jobs/job-abc/segments/0.mp4") == (
            "job-abc",
            0,
        )
        assert parse_output_segment_key("b", "jobs/xyz-123/segments/42.mp4") == (
            "xyz-123",
            42,
        )

    def test_final_mp4_returns_none(self) -> None:
        assert parse_output_segment_key("b", "jobs/job-abc/final.mp4") is None

    def test_invalid_patterns_return_none(self) -> None:
        assert parse_output_segment_key("b", "input/job/source.mp4") is None
        assert parse_output_segment_key("b", "jobs/") is None
        assert parse_output_segment_key("b", "jobs/job-abc/segments/") is None
        assert parse_output_segment_key("b", "jobs/job-abc/segments/foo.mp4") is None
        assert parse_output_segment_key("b", "jobs/job-abc/segments/-1.mp4") is None
        assert parse_output_segment_key("b", "jobs//segments/0.mp4") is None
