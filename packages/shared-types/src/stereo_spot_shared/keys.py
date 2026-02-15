"""
Segment and input key format and parsers.

Single source of truth: media-worker builds keys and video-worker parses them
using only these functions. No duplicate parsing logic elsewhere.

Segment key format: segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4
Input key format:   input/{job_id}/source.mp4

Parser behaviour: Invalid keys return None. Callers must check and handle accordingly.
"""

import re

from .models import StereoMode, VideoWorkerPayload

_SEGMENT_KEY_PREFIX = "segments/"
_SEGMENT_KEY_FILENAME_RE = re.compile(
    r"^(\d{5})_(\d{5})_(anaglyph|sbs)\.mp4$"
)
_INPUT_KEY_PREFIX = "input/"
_INPUT_KEY_SUFFIX = "/source.mp4"


def build_segment_key(
    job_id: str,
    segment_index: int,
    total_segments: int,
    mode: StereoMode,
) -> str:
    """
    Build the canonical segment object key.

    Format: segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4
    Zero-padding keeps lexicographic order and avoids ambiguity.
    """
    mode_val = mode.value if isinstance(mode, StereoMode) else mode
    return (
        f"{_SEGMENT_KEY_PREFIX}{job_id}/"
        f"{segment_index:05d}_{total_segments:05d}_{mode_val}.mp4"
    )


def parse_segment_key(bucket: str, key: str) -> VideoWorkerPayload | None:
    """
    Parse a segment object key into the canonical payload.

    Args:
        bucket: S3 bucket name.
        key: Object key (e.g. segments/job-abc/00042_00100_anaglyph.mp4).

    Returns:
        VideoWorkerPayload with job_id, segment_index, total_segments, mode,
        and segment_s3_uri (s3://bucket/key), or None if the key is invalid.
    """
    if not key.startswith(_SEGMENT_KEY_PREFIX):
        return None
    rest = key[len(_SEGMENT_KEY_PREFIX) :]
    if "/" not in rest:
        return None
    job_id, filename = rest.rsplit("/", 1)
    if not job_id:
        return None
    match = _SEGMENT_KEY_FILENAME_RE.match(filename)
    if not match:
        return None
    segment_index = int(match.group(1))
    total_segments = int(match.group(2))
    mode_str = match.group(3)
    try:
        mode = StereoMode(mode_str)
    except ValueError:
        return None
    if segment_index >= total_segments:
        return None
    segment_s3_uri = f"s3://{bucket}/{key}"
    return VideoWorkerPayload(
        job_id=job_id,
        segment_index=segment_index,
        total_segments=total_segments,
        segment_s3_uri=segment_s3_uri,
        mode=mode,
    )


def parse_input_key(key: str) -> str | None:
    """
    Parse an input object key to extract job_id.

    Expected format: input/{job_id}/source.mp4

    Args:
        key: Object key (e.g. input/job-abc/source.mp4).

    Returns:
        job_id if the key is valid, otherwise None.
    """
    if not key.startswith(_INPUT_KEY_PREFIX) or not key.endswith(_INPUT_KEY_SUFFIX):
        return None
    if len(key) <= len(_INPUT_KEY_PREFIX) + len(_INPUT_KEY_SUFFIX):
        return None
    job_id = key[len(_INPUT_KEY_PREFIX) : -len(_INPUT_KEY_SUFFIX)]
    if not job_id:
        return None
    return job_id
