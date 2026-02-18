"""Shared test helpers for video-worker tests."""

import json


def make_s3_event_body(bucket: str, key: str) -> str:
    """Build S3 event notification JSON body (Records[0].s3.bucket.name, object.key)."""
    return json.dumps({
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                }
            }
        ]
    })
