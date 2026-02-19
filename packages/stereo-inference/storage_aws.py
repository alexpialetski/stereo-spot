"""AWS S3 storage adapter. Download/upload via s3:// URIs."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import boto3


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Invalid S3 URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def download(uri: str, path: str) -> None:
    bucket, key = _parse_s3_uri(uri)
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    client = boto3.client("s3", region_name=region) if region else boto3.client("s3")
    client.download_file(bucket, key, path)


def upload(path: str, uri: str) -> None:
    bucket, key = _parse_s3_uri(uri)
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    client = boto3.client("s3", region_name=region) if region else boto3.client("s3")
    client.upload_file(path, bucket, key)
