"""
SageMaker inference backend: invoke an async endpoint with S3 URIs.

Uses InvokeEndpointAsync so inference can run longer than the 60s real-time limit.
The video-worker uploads the request JSON to S3, calls InvokeEndpointAsync, then
polls for the response object in S3 before returning.
"""

from __future__ import annotations

import json
import logging
import os
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Max time to wait for async inference response (seconds). Must be less than
# SQS visibility timeout; align with InvocationTimeoutSeconds on the request.
DEFAULT_ASYNC_POLL_TIMEOUT = 1200  # 20 minutes
DEFAULT_ASYNC_POLL_INTERVAL = 15   # seconds between HeadObject checks


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _job_id_segment_from_output_uri(output_s3_uri: str) -> tuple[str, str]:
    """Extract job_id and segment_index from output_s3_uri (e.g. s3://b/jobs/jid/segments/0.mp4)."""
    _, key = _parse_s3_uri(output_s3_uri)
    parts = key.split("/")
    if len(parts) >= 4 and parts[0] == "jobs" and parts[2] == "segments":
        seg = parts[3]
        segment_index = seg.replace(".mp4", "") if seg.endswith(".mp4") else seg
        return parts[1], segment_index
    raise ValueError(f"Cannot parse job_id/segment_index from output URI: {output_s3_uri}")


def invoke_sagemaker_endpoint(
    segment_s3_uri: str,
    output_s3_uri: str,
    endpoint_name: str,
    *,
    mode: str = "anaglyph",
    region_name: str | None = None,
    client: object | None = None,
) -> None:
    """
    Call SageMaker InvokeEndpointAsync: upload request to S3, invoke, poll for response.

    The endpoint reads the segment from segment_s3_uri, runs inference, and writes
    the result to output_s3_uri. Async allows inference to run up to 1 hour.

    Args:
        segment_s3_uri: S3 URI of the input segment.
        output_s3_uri: S3 URI where the endpoint should write the result.
        endpoint_name: SageMaker endpoint name (must be an async endpoint).
        mode: Output stereo format ("anaglyph" or "sbs").
        region_name: AWS region; if None, uses default.
        client: Optional boto3 sagemaker-runtime client (for testing).

    Raises:
        Exception: On invoke failure, timeout, or container error.
    """
    job_id, segment_index = _job_id_segment_from_output_uri(output_s3_uri)
    output_bucket, _ = _parse_s3_uri(output_s3_uri)
    request_key = f"sagemaker-invocation-requests/{job_id}/{segment_index}.json"
    request_s3_uri = f"s3://{output_bucket}/{request_key}"

    payload = {
        "s3_input_uri": segment_s3_uri,
        "s3_output_uri": output_s3_uri,
        "mode": mode,
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    if client is not None:
        sagemaker_runtime = client
        s3_client = None
    else:
        import boto3

        kwargs = {}
        if region_name:
            kwargs["region_name"] = region_name
        sagemaker_runtime = boto3.client("sagemaker-runtime", **kwargs)
        s3_client = boto3.client("s3", **kwargs)

    # Upload request payload to S3 (required for InvokeEndpointAsync input)
    if s3_client is not None:
        s3_client.put_object(
            Bucket=output_bucket,
            Key=request_key,
            Body=payload_bytes,
            ContentType="application/json",
        )
        logger.debug("job_id=%s segment_index=%s uploaded invocation request to %s", job_id, segment_index, request_s3_uri)

    invocation_timeout = DEFAULT_ASYNC_POLL_TIMEOUT
    env_timeout = os.environ.get("SAGEMAKER_INVOKE_TIMEOUT_SECONDS")
    if env_timeout is not None:
        try:
            invocation_timeout = int(env_timeout)
        except ValueError:
            pass

    response = sagemaker_runtime.invoke_endpoint_async(
        EndpointName=endpoint_name,
        InputLocation=request_s3_uri,
        InvocationTimeoutSeconds=min(invocation_timeout, 3600),
    )
    output_location = response["OutputLocation"]
    out_bucket, out_key = _parse_s3_uri(output_location)

    # Poll for response object (container writes success/error here)
    poll_timeout = invocation_timeout
    poll_interval = DEFAULT_ASYNC_POLL_INTERVAL
    env_interval = os.environ.get("SAGEMAKER_ASYNC_POLL_INTERVAL_SECONDS")
    if env_interval is not None:
        try:
            poll_interval = int(env_interval)
        except ValueError:
            pass

    deadline = time.monotonic() + poll_timeout
    if s3_client is None:
        import boto3
        s3_poll = boto3.client("s3", region_name=region_name)
    else:
        s3_poll = s3_client

    while time.monotonic() < deadline:
        try:
            obj = s3_poll.get_object(Bucket=out_bucket, Key=out_key)
            body = obj["Body"].read().decode("utf-8")
            data = json.loads(body)
            if data.get("error"):
                raise RuntimeError(f"Container error: {data.get('error')}")
            return
        except Exception as e:
            try:
                err_code = e.response["Error"]["Code"]
            except (KeyError, TypeError, AttributeError):
                err_code = ""
            if err_code in ("NoSuchKey", "404"):
                pass
            else:
                raise
        time.sleep(poll_interval)

    raise TimeoutError(
        f"Async inference did not produce output at {output_location} within {poll_timeout}s"
    )
