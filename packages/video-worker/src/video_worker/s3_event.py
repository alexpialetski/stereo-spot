"""
Parse S3 event notification payload from the video-worker queue message body.

S3 sends to SQS a JSON body with Records[].s3.bucket.name and Records[].s3.object.key.
The object key may be URL-encoded (e.g. %2F for /). We decode it then use
parse_segment_key from shared-types to get the canonical VideoWorkerPayload.
"""

import json
from typing import Any
from urllib.parse import unquote_plus

from stereo_spot_shared import VideoWorkerPayload, parse_segment_key


def parse_s3_event_body(body: str | bytes) -> VideoWorkerPayload | None:
    """
    Parse the S3 event notification body (JSON) into VideoWorkerPayload.

    Args:
        body: Raw message body from SQS (JSON string or bytes).

    Returns:
        VideoWorkerPayload if the body is valid S3 event and key is a segment key;
        None otherwise.
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
    # S3 event notifications may send the key URL-encoded (e.g. %2F for /).
    key = unquote_plus(key)
    return parse_segment_key(bucket_name, key)
