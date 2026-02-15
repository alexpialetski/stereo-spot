"""Tests for SageMaker inference backend (mocked invoke_endpoint)."""

import json
from unittest.mock import MagicMock, patch

from video_worker.model_sagemaker import invoke_sagemaker_endpoint


def test_invoke_sagemaker_endpoint_calls_client_with_correct_body() -> None:
    """invoke_sagemaker_endpoint sends JSON with s3_input_uri and s3_output_uri."""
    mock_client = MagicMock()
    segment_uri = "s3://input-bucket/segments/job-1/00000_00010_sbs.mp4"
    output_uri = "s3://output-bucket/jobs/job-1/segments/0.mp4"

    invoke_sagemaker_endpoint(
        segment_uri,
        output_uri,
        "my-endpoint",
        client=mock_client,
    )

    mock_client.invoke_endpoint.assert_called_once()
    call_kw = mock_client.invoke_endpoint.call_args[1]
    assert call_kw["EndpointName"] == "my-endpoint"
    assert call_kw["ContentType"] == "application/json"
    body = json.loads(call_kw["Body"].decode("utf-8"))
    assert body["s3_input_uri"] == segment_uri
    assert body["s3_output_uri"] == output_uri


def test_invoke_sagemaker_endpoint_uses_region_when_provided() -> None:
    """When region_name is passed and client is None, boto3.client gets region_name."""
    with patch("boto3.client") as mock_boto3_client:
        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client

        invoke_sagemaker_endpoint(
            "s3://in/seg.mp4",
            "s3://out/seg.mp4",
            "ep",
            region_name="us-west-2",
        )

        mock_boto3_client.assert_called_once_with(
            "sagemaker-runtime",
            region_name="us-west-2",
        )


def test_invoke_sagemaker_endpoint_uses_provided_client_not_boto3() -> None:
    """When client is provided, boto3.client is not used."""
    mock_client = MagicMock()
    with patch("boto3.client") as mock_boto3_client:
        invoke_sagemaker_endpoint(
            "s3://in/seg.mp4",
            "s3://out/seg.mp4",
            "ep",
            client=mock_client,
        )
        mock_boto3_client.assert_not_called()
    mock_client.invoke_endpoint.assert_called_once()
