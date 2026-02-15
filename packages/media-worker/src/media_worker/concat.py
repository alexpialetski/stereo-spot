"""
Build concat list from SegmentCompletions and run ffmpeg concat.

Uses SegmentCompletions only (no S3 list). Downloads segments to a temp dir,
writes an ffmpeg concat demuxer list file, runs ffmpeg -f concat -c copy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from stereo_spot_shared import SegmentCompletion
from stereo_spot_shared.interfaces import ObjectStorage


def _parse_s3_uri(s3_uri: str) -> tuple[str, str] | None:
    """Extract (bucket, key) from s3://bucket/key."""
    if not s3_uri.startswith("s3://"):
        return None
    rest = s3_uri[5:]
    if "/" not in rest:
        return None
    bucket, _, key = rest.partition("/")
    return bucket, key


def build_concat_list_paths(
    completions: list[SegmentCompletion],
    storage: ObjectStorage,
    output_bucket: str,
    segment_dir: Path,
) -> list[Path]:
    """
    Download each segment from completions (in order) to segment_dir and return
    local paths. Uses output_s3_uri from each completion; if that fails,
    uses deterministic path jobs/{job_id}/segments/{segment_index}.mp4 on output_bucket.
    """
    paths: list[Path] = []
    job_id = completions[0].job_id if completions else ""
    for i, comp in enumerate(completions):
        parsed = _parse_s3_uri(comp.output_s3_uri)
        if parsed:
            bucket, key = parsed
        else:
            bucket = output_bucket
            key = f"jobs/{job_id}/segments/{comp.segment_index}.mp4"
        data = storage.download(bucket, key)
        local_path = segment_dir / f"seg_{comp.segment_index:05d}.mp4"
        local_path.write_bytes(data)
        paths.append(local_path)
    return paths


def concat_segments_to_file(
    segment_paths: list[Path],
    output_path: str | Path,
) -> None:
    """
    Run ffmpeg concat demuxer to concatenate segment files into one output file.

    Writes a list file for ffmpeg -f concat -i list.txt -c copy output.
    Raises subprocess.CalledProcessError if ffmpeg fails.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_path = output_path.with_suffix(output_path.suffix + ".list")
    try:
        with open(list_path, "w") as f:
            for p in segment_paths:
                # ffmpeg concat format: file 'path' (escape single quotes in path)
                path_str = str(p.resolve()).replace("'", "'\\''")
                f.write(f"file '{path_str}'\n")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        if list_path.exists():
            list_path.unlink(missing_ok=True)
