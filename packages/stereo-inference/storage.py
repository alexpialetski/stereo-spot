"""Storage facade: download/upload by URI (s3://, gs://) using platform adapter (PLATFORM env)."""

from __future__ import annotations

from urllib.parse import urlparse

_storage = None


def _platform_storage():
    """Return ObjectStorage from facade (cached per process)."""
    global _storage
    if _storage is None:
        from stereo_spot_adapters.env_config import object_storage_from_env
        _storage = object_storage_from_env()
    return _storage


def _parse_uri(uri: str) -> tuple[str, str]:
    """Parse s3:// or gs:// URI into (bucket, key)."""
    parsed = urlparse(uri)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("s3", "gs"):
        raise ValueError(f"Unsupported URI scheme: {scheme}")
    if not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Invalid storage URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def download(uri: str, path: str) -> None:
    """Download object at URI to local path."""
    bucket, key = _parse_uri(uri)
    _platform_storage().download_file(bucket, key, path)


def upload(path: str, uri: str) -> None:
    """Upload local file to URI."""
    bucket, key = _parse_uri(uri)
    _platform_storage().upload_file(bucket, key, path)
