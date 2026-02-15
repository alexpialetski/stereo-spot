"""Tests for concat list building from SegmentCompletions."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from stereo_spot_shared import SegmentCompletion

from media_worker.concat import build_concat_list_paths, concat_segments_to_file


def test_build_concat_list_paths_orders_by_segment_index(
    tmp_path: Path,
) -> None:
    """build_concat_list_paths downloads segments in completion order and returns paths."""
    storage = MagicMock()
    storage.download.side_effect = [b"seg0", b"seg1", b"seg2"]
    completions = [
        SegmentCompletion(
            job_id="job-1",
            segment_index=1,
            output_s3_uri="s3://out/jobs/job-1/segments/1.mp4",
            completed_at=1001,
        ),
        SegmentCompletion(
            job_id="job-1",
            segment_index=0,
            output_s3_uri="s3://out/jobs/job-1/segments/0.mp4",
            completed_at=1000,
        ),
        SegmentCompletion(
            job_id="job-1",
            segment_index=2,
            output_s3_uri="s3://out/jobs/job-1/segments/2.mp4",
            completed_at=1002,
        ),
    ]
    completions_sorted = sorted(completions, key=lambda c: c.segment_index)
    paths = build_concat_list_paths(
        completions_sorted,
        storage,
        "output-bucket",
        tmp_path,
    )
    assert len(paths) == 3
    assert paths[0].read_bytes() == b"seg0"
    assert paths[1].read_bytes() == b"seg1"
    assert paths[2].read_bytes() == b"seg2"
    assert storage.download.call_count == 3
    assert storage.download.call_args_list[0][0][1] == "jobs/job-1/segments/0.mp4"


def test_concat_segments_to_file_writes_list_and_calls_ffmpeg(
    tmp_path: Path,
) -> None:
    """concat_segments_to_file writes concat list and invokes ffmpeg (mocked)."""
    seg0 = tmp_path / "s0.mp4"
    seg1 = tmp_path / "s1.mp4"
    seg0.write_bytes(b"fake0")
    seg1.write_bytes(b"fake1")
    out = tmp_path / "final.mp4"

    with patch("media_worker.concat.subprocess.run") as mock_run:
        def touch_output(*args, **kwargs):
            out.write_bytes(b"concat result")
            return MagicMock(returncode=0)

        mock_run.side_effect = touch_output
        concat_segments_to_file([seg0, seg1], out)

    assert out.exists()
    assert out.read_bytes() == b"concat result"
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "ffmpeg" in call_args
    assert "-f" in call_args and "concat" in call_args
    assert "-c" in call_args and "copy" in call_args
