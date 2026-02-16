"""
SageMaker inference backend: invoke a real-time endpoint with S3 URIs.

The endpoint reads the segment from s3_input_uri, runs inference (e.g. StereoCrafter),
and writes the stereo output directly to s3_output_uri. The video-worker does not
download or upload segment bytes.
"""

from __future__ import annotations

import json


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
    Call SageMaker InvokeEndpoint with S3 input/output URIs.

    The endpoint is expected to read the segment from segment_s3_uri, run inference,
    and write the result in the requested mode (anaglyph or sbs) to output_s3_uri.

    Args:
        segment_s3_uri: S3 URI of the input segment (e.g. s3://bucket/segments/...).
        output_s3_uri: S3 URI where the endpoint should write the result
            (e.g. s3://bucket/jobs/{job_id}/segments/{segment_index}.mp4).
        endpoint_name: SageMaker endpoint name.
        mode: Output stereo format ("anaglyph" or "sbs"); defaults to "anaglyph".
        region_name: AWS region for the endpoint; if None, uses default.
        client: Optional boto3 sagemaker-runtime client (for testing).
            If None, creates one via boto3.client("sagemaker-runtime", ...).

    Raises:
        Exception: On invoke failure (e.g. ClientError, timeout).
    """
    if client is not None:
        sagemaker_runtime = client
    else:
        import boto3

        kwargs = {}
        if region_name:
            kwargs["region_name"] = region_name
        sagemaker_runtime = boto3.client("sagemaker-runtime", **kwargs)

    body = json.dumps({
        "s3_input_uri": segment_s3_uri,
        "s3_output_uri": output_s3_uri,
        "mode": mode,
    }).encode("utf-8")

    sagemaker_runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="application/json",
        Body=body,
    )
