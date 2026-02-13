"""Tests for S3 event body parsing and input key extraction."""

import json

from stereo_spot_shared import parse_input_key

from chunking_worker.s3_event import parse_s3_event_body


def test_parse_valid_s3_event_input_key() -> None:
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
    assert payload is not None
    assert payload.bucket == "input-bucket"
    assert payload.key == "input/job-abc/source.mp4"
    assert parse_input_key(payload.key) == "job-abc"


def test_parse_s3_event_bytes_body() -> None:
    body = json.dumps({
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "b"},
                    "object": {"key": "input/xyz/source.mp4"},
                }
            }
        ]
    }).encode("utf-8")
    payload = parse_s3_event_body(body)
    assert payload is not None
    assert payload.bucket == "b"
    assert payload.key == "input/xyz/source.mp4"


def test_parse_s3_event_rejects_non_input_key() -> None:
    body = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "input-bucket"},
                    "object": {"key": "segments/job-abc/00000_00001_anaglyph.mp4"},
                }
            }
        ]
    }
    payload = parse_s3_event_body(json.dumps(body))
    assert payload is None


def test_parse_s3_event_invalid_json_returns_none() -> None:
    assert parse_s3_event_body("not json") is None
    assert parse_s3_event_body("") is None


def test_parse_s3_event_empty_records_returns_none() -> None:
    assert parse_s3_event_body(json.dumps({"Records": []})) is None
    assert parse_s3_event_body(json.dumps({})) is None


def test_parse_s3_event_malformed_record_returns_none() -> None:
    body = json.dumps({"Records": [{"s3": {"bucket": {}, "object": {}}}]})
    payload = parse_s3_event_body(body)
    assert payload is None
