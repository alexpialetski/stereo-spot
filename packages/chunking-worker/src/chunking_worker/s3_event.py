"""
Parse S3 event notification payload from the chunking queue message body.

S3 sends to SQS a JSON body with Records[].s3.bucket.name and Records[].s3.object.key.
We only care about the first record (one object per notification for our config).
"""

import json
from typing import Any

from stereo_spot_shared import ChunkingPayload, parse_input_key


def parse_s3_event_body(body: str | bytes) -> ChunkingPayload | None:
    """
    Parse the S3 event notification body (JSON) into ChunkingPayload.

    Args:
        body: Raw message body from SQS (JSON string or bytes).

    Returns:
        ChunkingPayload(bucket, key) if the body is valid S3 event and key is
        an input key (input/{job_id}/source.mp4); None otherwise.
    """
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    try:
        data: dict[str, Any] = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    records = data.get("Records")
    if not records or not isinstance(records, list):
        return None
    first = records[0]
    if not isinstance(first, dict):
        return None
    s3_data = first.get("s3")
    if not isinstance(s3_data, dict):
        return None
    bucket_obj = s3_data.get("bucket")
    object_obj = s3_data.get("object")
    if not isinstance(bucket_obj, dict) or not isinstance(object_obj, dict):
        return None
    bucket_name = bucket_obj.get("name")
    key = object_obj.get("key")
    if not isinstance(bucket_name, str) or not isinstance(key, str):
        return None
    if not bucket_name or not key:
        return None
    # Only accept input keys (input/{job_id}/source.mp4)
    if parse_input_key(key) is None:
        return None
    return ChunkingPayload(bucket=bucket_name, key=key)
