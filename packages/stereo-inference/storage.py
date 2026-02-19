"""Storage adapter facade. Routes download/upload by URI scheme (s3://, gs://) or STORAGE_PROVIDER env."""

from __future__ import annotations

import os
from urllib.parse import urlparse


def _scheme_for_uri(uri: str) -> str:
    parsed = urlparse(uri)
    return (parsed.scheme or "").lower()


def _get_provider_for_uri(uri: str) -> str:
    scheme = _scheme_for_uri(uri)
    if scheme == "s3":
        return "aws"
    if scheme == "gs":
        return "gcp"
    raise ValueError(f"Unsupported URI scheme: {scheme}")


def download(uri: str, path: str) -> None:
    provider = (os.environ.get("STORAGE_PROVIDER") or "").strip().lower() or _get_provider_for_uri(uri)
    if provider == "aws":
        import storage_aws
        storage_aws.download(uri, path)
    elif provider == "gcp":
        import storage_gcp
        storage_gcp.download(uri, path)
    else:
        raise ValueError(f"Unsupported STORAGE_PROVIDER: {provider}")


def upload(path: str, uri: str) -> None:
    provider = (os.environ.get("STORAGE_PROVIDER") or "").strip().lower() or _get_provider_for_uri(uri)
    if provider == "aws":
        import storage_aws
        storage_aws.upload(path, uri)
    elif provider == "gcp":
        import storage_gcp
        storage_gcp.upload(path, uri)
    else:
        raise ValueError(f"Unsupported STORAGE_PROVIDER: {provider}")
