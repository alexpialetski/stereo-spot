"""
HTTP inference backend: POST to an inference server that implements the same contract as SageMaker.

The server at base_url must expose POST /invocations with JSON body
{s3_input_uri, s3_output_uri, mode}. Used for dev/testing (e.g. EC2 running the same container).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def invoke_http_endpoint(
    base_url: str,
    segment_s3_uri: str,
    output_s3_uri: str,
    *,
    mode: str = "anaglyph",
    timeout: int = 3600,
) -> None:
    """
    POST to base_url/invocations with the same JSON body as SageMaker InvokeEndpoint.

    Args:
        base_url: Base URL of the inference server (e.g. http://10.0.1.5:8080).
        segment_s3_uri: S3 URI of the input segment.
        output_s3_uri: S3 URI where the server should write the result.
        mode: Output stereo format ("anaglyph" or "sbs").
        timeout: Request timeout in seconds (inference can be long).

    Raises:
        Exception: On HTTP error or timeout.
    """
    url = base_url.rstrip("/") + "/invocations"
    body = json.dumps({
        "s3_input_uri": segment_s3_uri,
        "s3_output_uri": output_s3_uri,
        "mode": mode,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {resp.read().decode()}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Request failed: {e.reason}")
