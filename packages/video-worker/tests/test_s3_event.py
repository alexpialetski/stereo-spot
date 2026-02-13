"""Tests for S3 event body parsing (segment key -> VideoWorkerPayload)."""

import json

from stereo_spot_shared import StereoMode

from video_worker.s3_event import parse_s3_event_body


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
