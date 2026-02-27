"""Tests for S3 event body parsing (segment key -> VideoWorkerPayload)."""

import json

from stereo_spot_shared import StereoMode

from video_worker.s3_event import (
    parse_s3_event_body,
    parse_s3_event_bucket_key,
    parse_video_worker_message,
)


def test_parse_valid_s3_event_segment_key() -> None:
    body = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "input-bucket"},
                    "object": {"key": "segments/job-abc/00042_00100_anaglyph.mp4"},
                }
            }
        ]
    }
    payload = parse_s3_event_body(json.dumps(body))
    assert payload is not None
    assert payload.job_id == "job-abc"
    assert payload.segment_index == 42
    assert payload.total_segments == 100
    assert payload.mode == StereoMode.ANAGLYPH
    assert payload.segment_s3_uri == "s3://input-bucket/segments/job-abc/00042_00100_anaglyph.mp4"


def test_parse_s3_event_rejects_input_key() -> None:
    body = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "input-bucket"},
                    "object": {"key": "input/job-abc/source.mp4"},
                }
            }
        ]
    }
    payload = parse_s3_event_body(json.dumps(body))
    assert payload is None


def test_parse_s3_event_invalid_json_returns_none() -> None:
    assert parse_s3_event_body("not json") is None


def test_parse_s3_event_empty_records_returns_none() -> None:
    assert parse_s3_event_body(json.dumps({"Records": []})) is None


def test_parse_s3_event_accepts_url_encoded_key() -> None:
    """S3 event notifications may send the object key URL-encoded."""
    body = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "input-bucket"},
                    "object": {"key": "segments%2Fjob-xyz%2F00000_00001_sbs.mp4"},
                }
            }
        ]
    }
    payload = parse_s3_event_body(json.dumps(body))
    assert payload is not None
    assert payload.job_id == "job-xyz"
    assert payload.segment_index == 0
    assert payload.total_segments == 1
    assert payload.segment_s3_uri == "s3://input-bucket/segments/job-xyz/00000_00001_sbs.mp4"


def test_parse_s3_event_bucket_key_valid() -> None:
    """parse_s3_event_bucket_key returns (bucket, key) for valid S3 event."""
    body = json.dumps({
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "output-bucket"},
                    "object": {"key": "jobs/job-abc/segments/2.mp4"},
                }
            }
        ]
    })
    result = parse_s3_event_bucket_key(body)
    assert result == ("output-bucket", "jobs/job-abc/segments/2.mp4")


def test_parse_s3_event_bucket_key_invalid_returns_none() -> None:
    assert parse_s3_event_bucket_key("not json") is None
    assert parse_s3_event_bucket_key(json.dumps({"Records": []})) is None


def test_parse_video_worker_message_batch() -> None:
    """parse_video_worker_message returns (VideoWorkerPayload, 'batch') for segments/ key."""
    body = json.dumps({
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "input-bucket"},
                    "object": {"key": "segments/job-xyz/00001_00005_sbs.mp4"},
                }
            }
        ]
    })
    payload, kind = parse_video_worker_message(body, "output-bucket")
    assert kind == "batch"
    assert payload is not None
    assert payload.job_id == "job-xyz"
    assert payload.segment_index == 1
    assert payload.total_segments == 5
    assert payload.mode == StereoMode.SBS


def test_parse_video_worker_message_stream() -> None:
    """parse_video_worker_message returns (StreamChunkPayload, 'stream') for stream_input/ key."""
    body = json.dumps({
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "input-bucket"},
                    "object": {"key": "stream_input/session-abc/chunk_00042.mp4"},
                }
            }
        ]
    })
    payload, kind = parse_video_worker_message(body, "output-bucket")
    assert kind == "stream"
    assert payload is not None
    assert payload.session_id == "session-abc"
    assert payload.chunk_index == 42
    assert payload.input_s3_uri == "s3://input-bucket/stream_input/session-abc/chunk_00042.mp4"
    assert payload.output_s3_uri == "s3://output-bucket/stream_output/session-abc/seg_00042.mp4"
    assert payload.mode == StereoMode.SBS


def test_parse_video_worker_message_invalid_returns_none_none() -> None:
    payload, kind = parse_video_worker_message("not json", "output-bucket")
    assert payload is None
    assert kind is None
