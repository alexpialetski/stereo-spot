"""
Shared S3 URI parsing. Single place for s3://bucket/key handling.
"""

from urllib.parse import urlparse


def parse_s3_uri(s3_uri: str) -> tuple[str, str] | None:
    """
    Extract (bucket, key) from an S3 URI.

    Args:
        s3_uri: e.g. s3://my-bucket/path/to/object.mp4

    Returns:
        (bucket, key) or None if the URI is invalid.
    """
    if not s3_uri or not isinstance(s3_uri, str):
        return None
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        return None
    return parsed.netloc, parsed.path.lstrip("/")


def parse_s3_uri_or_raise(s3_uri: str) -> tuple[str, str]:
    """Like parse_s3_uri but raises ValueError if invalid."""
    result = parse_s3_uri(s3_uri)
    if result is None:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return result
