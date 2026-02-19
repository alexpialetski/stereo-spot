"""
SageMaker inference backend: invoke an async endpoint with S3 URIs.

Uses InvokeEndpointAsync so inference can run longer than the 60s real-time limit.
The video-worker uploads the request JSON to S3, calls InvokeEndpointAsync, then
polls for the response object in S3 before returning.
"""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlparse

from .config import get_settings

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


def invoke_sagemaker_async(
    segment_s3_uri: str,
    output_s3_uri: str,
    endpoint_name: str,
    *,
    mode: str = "anaglyph",
    region_name: str | None = None,
    client: object | None = None,
) -> str:
    """
    Upload request to S3 and call InvokeEndpointAsync. Returns the OutputLocation (S3 URI).

    Does not poll; use poll_async_response() to wait for the result.

    Args:
        segment_s3_uri: S3 URI of the input segment.
        output_s3_uri: S3 URI where the endpoint should write the result.
        endpoint_name: SageMaker endpoint name (must be an async endpoint).
        mode: Output stereo format ("anaglyph" or "sbs").
        region_name: AWS region; if None, uses default.
        client: Optional boto3 sagemaker-runtime client (for testing).

    Returns:
        OutputLocation S3 URI where the async response will appear.
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

    if s3_client is not None:
        s3_client.put_object(
            Bucket=output_bucket,
            Key=request_key,
            Body=payload_bytes,
            ContentType="application/json",
        )
        logger.debug(
            "job_id=%s segment_index=%s uploaded invocation request to %s",
            job_id, segment_index, request_s3_uri,
        )

    invocation_timeout = min(
        get_settings().sagemaker_invoke_timeout_seconds,
        3600,
    )

    response = sagemaker_runtime.invoke_endpoint_async(
        EndpointName=endpoint_name,
        InputLocation=request_s3_uri,
        InvocationTimeoutSeconds=min(invocation_timeout, 3600),
    )
    return response["OutputLocation"]


def poll_async_response(
    output_location: str,
    *,
    timeout: float | None = None,
    interval: float | None = None,
    s3_client: object | None = None,
) -> None:
    """
    Poll the async response S3 path until success JSON (return) or error JSON (raise).

    Args:
        output_location: S3 URI of the async response object.
        timeout: Max seconds to wait; default from env or DEFAULT_ASYNC_POLL_TIMEOUT.
        interval: Seconds between checks; default from env or DEFAULT_ASYNC_POLL_INTERVAL.
        s3_client: Optional boto3 S3 client (for testing); if None, one is created.

    Raises:
        RuntimeError: If container returned an error in the response JSON.
        TimeoutError: If no response object within timeout.
    """
    out_bucket, out_key = _parse_s3_uri(output_location)
    s = get_settings()
    poll_timeout = timeout if timeout is not None else float(s.sagemaker_invoke_timeout_seconds)
    poll_interval = (
        interval if interval is not None else float(s.sagemaker_async_poll_interval_seconds)
    )

    if s3_client is not None:
        s3_poll = s3_client
    else:
        import boto3
        s3_poll = boto3.client("s3")

    deadline = time.monotonic() + poll_timeout
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


def check_async_response_once(
    output_location: str,
    s3_client: object,
) -> str:
    """
    Non-blocking check of the async response S3 object.
    Returns "success", "error", or "pending".
    """
    out_bucket, out_key = _parse_s3_uri(output_location)
    try:
        obj = s3_client.get_object(Bucket=out_bucket, Key=out_key)
        body = obj["Body"].read().decode("utf-8")
        data = json.loads(body)
        if data.get("error"):
            return "error"
        return "success"
    except Exception as e:
        try:
            err_code = e.response["Error"]["Code"]
        except (KeyError, TypeError, AttributeError):
            err_code = ""
        if err_code in ("NoSuchKey", "404"):
            return "pending"
        raise


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

    Kept for backward compatibility; implemented as invoke_sagemaker_async + poll_async_response.
    """
    output_location = invoke_sagemaker_async(
        segment_s3_uri,
        output_s3_uri,
        endpoint_name,
        mode=mode,
        region_name=region_name,
        client=client,
    )
    if client is not None:
        s3_client = None
    else:
        import boto3
        kwargs = {}
        if region_name:
            kwargs["region_name"] = region_name
        s3_client = boto3.client("s3", **kwargs)
    poll_async_response(output_location, s3_client=s3_client)
