"""Tests for storage facade: URI scheme and provider selection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import storage


def test_scheme_for_uri_s3() -> None:
    assert storage._scheme_for_uri("s3://bucket/key") == "s3"
    assert storage._scheme_for_uri("S3://b/k") == "s3"


def test_scheme_for_uri_gs() -> None:
    assert storage._scheme_for_uri("gs://bucket/path") == "gs"


def test_scheme_for_uri_empty() -> None:
    assert storage._scheme_for_uri("no-scheme") == ""


def test_get_provider_for_uri_s3() -> None:
    assert storage._get_provider_for_uri("s3://b/k") == "aws"


def test_get_provider_for_uri_gs() -> None:
    assert storage._get_provider_for_uri("gs://b/k") == "gcp"


def test_get_provider_for_uri_unsupported() -> None:
    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        storage._get_provider_for_uri("http://example.com/path")


def test_download_uses_aws_when_s3_uri() -> None:
    with patch("storage_aws.download") as mock_aws:
        storage.download("s3://bucket/key", "/tmp/p")
        mock_aws.assert_called_once_with("s3://bucket/key", "/tmp/p")


def test_download_uses_gcp_when_gs_uri() -> None:
    with patch("storage_gcp.download") as mock_gcp:
        storage.download("gs://bucket/key", "/tmp/p")
        mock_gcp.assert_called_once_with("gs://bucket/key", "/tmp/p")


def test_download_uses_storage_provider_over_uri() -> None:
    with patch.dict("os.environ", {"STORAGE_PROVIDER": "gcp"}):
        with patch("storage_gcp.download") as mock_gcp:
            storage.download("s3://bucket/key", "/tmp/p")
            mock_gcp.assert_called_once_with("s3://bucket/key", "/tmp/p")


def test_upload_uses_aws_when_s3_uri() -> None:
    with patch("storage_aws.upload") as mock_aws:
        storage.upload("/tmp/p", "s3://bucket/key")
        mock_aws.assert_called_once_with("/tmp/p", "s3://bucket/key")


def test_upload_uses_gcp_when_gs_uri() -> None:
    with patch("storage_gcp.upload") as mock_gcp:
        storage.upload("/tmp/p", "gs://bucket/key")
        mock_gcp.assert_called_once_with("/tmp/p", "gs://bucket/key")


def test_download_unsupported_provider() -> None:
    with patch.dict("os.environ", {"STORAGE_PROVIDER": "azure"}):
        with pytest.raises(ValueError, match="Unsupported STORAGE_PROVIDER"):
            storage.download("s3://b/k", "/tmp/p")
