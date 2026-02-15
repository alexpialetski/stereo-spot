"""
FFmpeg-based video chunking: keyframe-aligned segments by duration.

Uses -f segment -segment_time with -c copy for keyframe-aligned splits without re-encoding.
"""

import subprocess
import tempfile
from pathlib import Path

DEFAULT_SEGMENT_DURATION_SEC = 300  # ~5 min


def chunk_video(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    segment_duration_sec: int = DEFAULT_SEGMENT_DURATION_SEC,
) -> list[Path]:
    """
    Split the input video into keyframe-aligned segments.

    Args:
        input_path: Path to the source video file.
        output_dir: Directory where segment files will be written.
        segment_duration_sec: Target duration per segment in seconds (~5 min default).

    Returns:
        List of paths to segment files (segment_00000.mp4, segment_00001.mp4, ...)
        in order. The output_dir is used as-is; segment names are chosen by ffmpeg
        segment muxer (default pattern segment_%05d).

    Raises:
        subprocess.CalledProcessError: If ffmpeg fails.
        FileNotFoundError: If ffmpeg is not installed.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # ffmpeg segment muxer with -c copy: keyframe-aligned, no re-encode
    # Output pattern: segment_00000.mp4, segment_00001.mp4, ...
    segment_pattern = output_dir / "segment_%05d.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-f",
        "segment",
        "-segment_time",
        str(segment_duration_sec),
        "-reset_timestamps",
        "1",
        "-c",
        "copy",
        "-map",
        "0",
        str(segment_pattern),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    # Collect produced files in order
    segments: list[Path] = []
    i = 0
    while True:
        p = output_dir / f"segment_{i:05d}.mp4"
        if not p.exists():
            break
        segments.append(p)
        i += 1
    return segments


def chunk_video_to_temp(
    input_path: str | Path,
    *,
    segment_duration_sec: int = DEFAULT_SEGMENT_DURATION_SEC,
) -> tuple[list[Path], tempfile.TemporaryDirectory]:
    """
    Chunk the video into a temporary directory. Caller must clean up the temp dir.

    Returns:
        (list of segment paths, TemporaryDirectory instance).
    """
    tmp = tempfile.TemporaryDirectory(prefix="chunking_")
    segments = chunk_video(
        input_path, tmp.name, segment_duration_sec=segment_duration_sec
    )
    return segments, tmp
