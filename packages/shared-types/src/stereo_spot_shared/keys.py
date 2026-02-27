"""
Segment and input key format and parsers.

Single source of truth: media-worker builds keys and video-worker parses them
using only these functions. No duplicate parsing logic elsewhere.

Segment key format: segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4
Input key format:   input/{job_id}/source.mp4
Output segment key: jobs/{job_id}/segments/{segment_index}.mp4

Parser behaviour: Invalid keys return None. Callers must check and handle accordingly.
"""

import re
from typing import overload

from .models import StereoMode, StreamChunkPayload, VideoWorkerPayload

_SEGMENT_KEY_PREFIX = "segments/"
_OUTPUT_SEGMENT_KEY_PREFIX = "jobs/"
_OUTPUT_SEGMENT_KEY_SUFFIX_RE = re.compile(r"^segments/(\d+)\.mp4$")
_SEGMENT_KEY_FILENAME_RE = re.compile(
    r"^(\d{5})_(\d{5})_(anaglyph|sbs)\.mp4$"
)
_INPUT_KEY_PREFIX = "input/"
_INPUT_KEY_SUFFIX = "/source.mp4"
_STREAM_INPUT_PREFIX = "stream_input/"
_STREAM_CHUNK_FILENAME_RE = re.compile(r"^chunk_(\d{5})\.mp4$")
_STREAM_OUTPUT_PREFIX = "stream_output/"


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


def parse_output_segment_key(bucket: str, key: str) -> tuple[str, int] | None:
    """
    Parse an output-bucket segment object key into job_id and segment_index.

    Expected format: jobs/{job_id}/segments/{segment_index}.mp4

    Args:
        bucket: S3 bucket name.
        key: Object key (e.g. jobs/job-abc/segments/0.mp4).

    Returns:
        (job_id, segment_index) if the key is valid, otherwise None.
        Returns None for keys like jobs/{job_id}/final.mp4 (not a segment).
    """
    if not key.startswith(_OUTPUT_SEGMENT_KEY_PREFIX):
        return None
    rest = key[len(_OUTPUT_SEGMENT_KEY_PREFIX) :]
    if "/" not in rest:
        return None
    job_id, remainder = rest.split("/", 1)
    if not job_id:
        return None
    match = _OUTPUT_SEGMENT_KEY_SUFFIX_RE.match(remainder)
    if not match:
        return None
    segment_index = int(match.group(1))
    if segment_index < 0:
        return None
    return (job_id, segment_index)


@overload
def parse_stream_chunk_key(
    bucket: str,
    key: str,
    *,
    output_bucket: None = None,
    default_mode: StereoMode | str = StereoMode.SBS,
) -> StreamChunkPayload | None:
    ...


@overload
def parse_stream_chunk_key(
    bucket: str,
    key: str,
    *,
    output_bucket: str,
    default_mode: StereoMode | str = StereoMode.SBS,
) -> StreamChunkPayload | None:
    ...


def parse_stream_chunk_key(
    bucket: str,
    key: str,
    *,
    output_bucket: str | None = None,
    default_mode: StereoMode | str = StereoMode.SBS,
) -> StreamChunkPayload | None:
    """
    Parse a streaming chunk key into the canonical StreamChunkPayload.

    Expected input key format: stream_input/{session_id}/chunk_{index:05d}.mp4

    Args:
        bucket: Input S3 bucket name.
        key: Object key under the input bucket.
        output_bucket: Optional output bucket name; when provided, output_s3_uri
            is populated using stream_output/{session_id}/seg_{index:05d}.mp4.
        default_mode: Mode to use when no session metadata is available; must
            be a valid StereoMode value (e.g. StereoMode.SBS).

    Returns:
        StreamChunkPayload with session_id, chunk_index, input_s3_uri, optional
        output_s3_uri, and mode, or None if the key is invalid.
    """
    if not key.startswith(_STREAM_INPUT_PREFIX):
        return None
    rest = key[len(_STREAM_INPUT_PREFIX) :]
    if "/" not in rest:
        return None
    session_id, filename = rest.split("/", 1)
    if not session_id:
        return None
    match = _STREAM_CHUNK_FILENAME_RE.match(filename)
    if not match:
        return None
    chunk_index = int(match.group(1))
    if chunk_index < 0:
        return None

    mode_value = default_mode.value if isinstance(default_mode, StereoMode) else default_mode
    try:
        mode = StereoMode(mode_value)
    except ValueError:
        return None

    input_s3_uri = f"s3://{bucket}/{key}"
    output_s3_uri: str | None = None
    if output_bucket is not None:
        output_s3_uri = (
            f"s3://{output_bucket}/{_STREAM_OUTPUT_PREFIX}"
            f"{session_id}/seg_{chunk_index:05d}.mp4"
        )

    return StreamChunkPayload(
        session_id=session_id,
        chunk_index=chunk_index,
        input_s3_uri=input_s3_uri,
        output_s3_uri=output_s3_uri,
        mode=mode,
    )
