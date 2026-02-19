"""Tests for AWS S3 storage adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import storage_aws


def test_parse_s3_uri() -> None:
    bucket, key = storage_aws._parse_s3_uri("s3://my-bucket/path/to/obj.mp4")
    assert bucket == "my-bucket"
    assert key == "path/to/obj.mp4"


def test_parse_s3_uri_root_key() -> None:
    bucket, key = storage_aws._parse_s3_uri("s3://b/file")
    assert bucket == "b"
    assert key == "file"


def test_parse_s3_uri_invalid_scheme() -> None:
    with pytest.raises(ValueError, match="Invalid S3 URI"):
        storage_aws._parse_s3_uri("gs://b/k")


def test_parse_s3_uri_no_netloc() -> None:
    with pytest.raises(ValueError, match="Invalid S3 URI"):
        storage_aws._parse_s3_uri("s3:///key")


def test_download_calls_boto3() -> None:
    mock_client = MagicMock()
    with patch("storage_aws.boto3.client", return_value=mock_client):
        storage_aws.download("s3://bucket/key", "/tmp/local")
    mock_client.download_file.assert_called_once_with("bucket", "key", "/tmp/local")


def test_upload_calls_boto3() -> None:
    mock_client = MagicMock()
    with patch("storage_aws.boto3.client", return_value=mock_client):
        storage_aws.upload("/tmp/local", "s3://bucket/key")
    mock_client.upload_file.assert_called_once_with("/tmp/local", "bucket", "key")


def test_download_uses_region_from_env() -> None:
    mock_client = MagicMock()
    with patch.dict("os.environ", {"AWS_REGION": "us-west-2"}):
        with patch("storage_aws.boto3.client", return_value=mock_client) as mock_boto:
            storage_aws.download("s3://b/k", "/tmp/p")
    mock_boto.assert_called_once_with("s3", region_name="us-west-2")
