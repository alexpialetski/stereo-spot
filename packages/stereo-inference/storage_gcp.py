"""GCP GCS storage adapter. Download/upload via gs:// URIs."""

from __future__ import annotations

from urllib.parse import urlparse

try:
    from google.cloud import storage as gcs_storage
except ImportError:
    gcs_storage = None


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Invalid GCS URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def download(uri: str, path: str) -> None:
    if gcs_storage is None:
        raise RuntimeError("google-cloud-storage is not installed; pip install google-cloud-storage")
    bucket_name, blob_name = _parse_gs_uri(uri)
    client = gcs_storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(path)


def upload(path: str, uri: str) -> None:
    if gcs_storage is None:
        raise RuntimeError("google-cloud-storage is not installed; pip install google-cloud-storage")
    bucket_name, blob_name = _parse_gs_uri(uri)
    client = gcs_storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(path)
