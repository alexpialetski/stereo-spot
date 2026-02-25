"""Tests for storage facade: URI parsing and platform adapter delegation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import storage


def test_parse_uri_s3() -> None:
    bucket, key = storage._parse_uri("s3://my-bucket/path/to/obj.mp4")
    assert bucket == "my-bucket"
    assert key == "path/to/obj.mp4"


def test_parse_uri_s3_root_key() -> None:
    bucket, key = storage._parse_uri("s3://b/file")
    assert bucket == "b"
    assert key == "file"


def test_parse_uri_gs() -> None:
    bucket, key = storage._parse_uri("gs://my-bucket/path/to/obj.mp4")
    assert bucket == "my-bucket"
    assert key == "path/to/obj.mp4"


def test_parse_uri_unsupported_scheme() -> None:
    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        storage._parse_uri("http://example.com/path")


def test_parse_uri_invalid_no_netloc() -> None:
    with pytest.raises(ValueError, match="Invalid storage URI"):
        storage._parse_uri("s3:///key")


def test_download_calls_storage_download_file() -> None:
    mock_storage = MagicMock()
    import storage as storage_mod
    storage_mod._storage = None
    with patch("stereo_spot_adapters.env_config.object_storage_from_env", return_value=mock_storage):
        storage.download("s3://bucket/key", "/tmp/p")
    mock_storage.download_file.assert_called_once_with("bucket", "key", "/tmp/p")


def test_upload_calls_storage_upload_file() -> None:
    mock_storage = MagicMock()
    import storage as storage_mod
    storage_mod._storage = None
    with patch("stereo_spot_adapters.env_config.object_storage_from_env", return_value=mock_storage):
        storage.upload("/tmp/p", "s3://bucket/key")
    mock_storage.upload_file.assert_called_once_with("bucket", "key", "/tmp/p")
