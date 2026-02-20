"""Tests for shared S3 URI parsing."""

import pytest

from video_worker.s3_uri import parse_s3_uri, parse_s3_uri_or_raise


def test_parse_s3_uri_valid() -> None:
    bucket, key = parse_s3_uri("s3://my-bucket/path/to/object.mp4")
    assert bucket == "my-bucket"
    assert key == "path/to/object.mp4"


def test_parse_s3_uri_root_key() -> None:
    bucket, key = parse_s3_uri("s3://b/k")
    assert bucket == "b"
    assert key == "k"


def test_parse_s3_uri_returns_none_for_invalid() -> None:
    assert parse_s3_uri("") is None
    assert parse_s3_uri("http://b/k") is None
    assert parse_s3_uri("s3://") is None
    assert parse_s3_uri("s3://bucket") is None  # no key
    assert parse_s3_uri("not-a-uri") is None


def test_parse_s3_uri_or_raise_valid() -> None:
    bucket, key = parse_s3_uri_or_raise("s3://b/path")
    assert bucket == "b"
    assert key == "path"


def test_parse_s3_uri_or_raise_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Invalid S3 URI"):
        parse_s3_uri_or_raise("s3://")
    with pytest.raises(ValueError, match="Invalid S3 URI"):
        parse_s3_uri_or_raise("http://b/k")
