"""Tests for SageMaker async inference backend (mocked invoke_endpoint_async and S3)."""

from io import BytesIO
from unittest.mock import MagicMock, patch

from video_worker.model_sagemaker import invoke_sagemaker_async, invoke_sagemaker_endpoint


def _make_s3_mock_success():
    """S3 client mock: get_object returns container success body."""
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": BytesIO(b'{"status":"ok"}')}
    return s3


def test_invoke_sagemaker_endpoint_calls_async_with_input_location() -> None:
    """invoke_sagemaker_endpoint_async is called with InputLocation derived from output_uri."""
    mock_client = MagicMock()
    mock_client.invoke_endpoint_async.return_value = {
        "OutputLocation": "s3://output-bucket/sagemaker-async-responses/req-123",
    }
    segment_uri = "s3://input-bucket/segments/job-1/00000_00010_sbs.mp4"
    output_uri = "s3://output-bucket/jobs/job-1/segments/0.mp4"

    with patch("boto3.client", return_value=_make_s3_mock_success()):
        invoke_sagemaker_endpoint(
            segment_uri,
            output_uri,
            "my-endpoint",
            mode="sbs",
            client=mock_client,
        )

    mock_client.invoke_endpoint_async.assert_called_once()
    call_kw = mock_client.invoke_endpoint_async.call_args[1]
    assert call_kw["EndpointName"] == "my-endpoint"
    expected = "s3://output-bucket/sagemaker-invocation-requests/job-1/0.json"
    assert expected == call_kw["InputLocation"]
    assert call_kw["InvocationTimeoutSeconds"] <= 3600


def test_invoke_sagemaker_endpoint_defaults_to_anaglyph_mode() -> None:
    """When mode omitted, InputLocation path reflects anaglyph; async is used."""
    mock_client = MagicMock()
    mock_client.invoke_endpoint_async.return_value = {
        "OutputLocation": "s3://out/resp",
    }
    with patch("boto3.client", return_value=_make_s3_mock_success()):
        invoke_sagemaker_endpoint(
            "s3://in/seg.mp4",
            "s3://out/jobs/j1/segments/0.mp4",
            "ep",
            client=mock_client,
        )
    mock_client.invoke_endpoint_async.assert_called_once()
    loc = mock_client.invoke_endpoint_async.call_args[1]["InputLocation"]
    assert "sagemaker-invocation-requests/j1/0.json" in loc


def test_invoke_sagemaker_endpoint_uses_region_when_provided() -> None:
    """When region_name is passed and client is None, boto3.client gets region_name."""
    sagemaker_mock = MagicMock()
    sagemaker_mock.invoke_endpoint_async.return_value = {
        "OutputLocation": "s3://out/resp",
    }
    s3_mock = _make_s3_mock_success()
    # invoke_async creates sagemaker+s3; invoke_sagemaker_endpoint creates s3 again for poll
    with patch("boto3.client", side_effect=[sagemaker_mock, s3_mock, s3_mock]) as mock_boto3_client:
        invoke_sagemaker_endpoint(
            "s3://in/seg.mp4",
            "s3://out/jobs/j1/segments/0.mp4",
            "ep",
            region_name="us-west-2",
        )
        assert mock_boto3_client.call_count >= 2
        first_kw = mock_boto3_client.call_args_list[0][1]
        assert first_kw.get("region_name") == "us-west-2"


def test_invoke_sagemaker_endpoint_uses_provided_client_not_boto3_for_runtime() -> None:
    """Provided client gets invoke_endpoint_async; S3 client created for upload and for polling."""
    mock_client = MagicMock()
    mock_client.invoke_endpoint_async.return_value = {
        "OutputLocation": "s3://out/resp",
    }
    s3_mock = _make_s3_mock_success()
    with patch("boto3.client", return_value=s3_mock) as mock_boto3_client:
        invoke_sagemaker_endpoint(
            "s3://in/seg.mp4",
            "s3://out/jobs/j1/segments/0.mp4",
            "ep",
            client=mock_client,
        )
        mock_client.invoke_endpoint_async.assert_called_once()
        # S3 client created in invoke_sagemaker_async (upload) and in
        # invoke_sagemaker_endpoint (poll)
        assert mock_boto3_client.call_count >= 2
        assert all(c[0][0] == "s3" for c in mock_boto3_client.call_args_list)


def test_invoke_sagemaker_async_uploads_request_when_client_passed() -> None:
    """When client (sagemaker-runtime) is passed, S3 put_object must still be called.

    This test would have caught the bug where s3_client was set to None when client
    was provided, so the invocation request was never uploaded and SageMaker failed
    to download it.
    """
    sagemaker_mock = MagicMock()
    sagemaker_mock.invoke_endpoint_async.return_value = {
        "OutputLocation": "s3://out-bucket/sagemaker-async-responses/req-1",
    }
    s3_mock = MagicMock()
    with patch("boto3.client", return_value=s3_mock):
        invoke_sagemaker_async(
            "s3://input/segments/job-1/00000_00001_anaglyph.mp4",
            "s3://output-bucket/jobs/job-1/segments/0.mp4",
            "my-endpoint",
            mode="anaglyph",
            client=sagemaker_mock,
        )
    s3_mock.put_object.assert_called_once()
    call_kw = s3_mock.put_object.call_args[1]
    assert call_kw["Bucket"] == "output-bucket"
    assert call_kw["Key"] == "sagemaker-invocation-requests/job-1/0.json"
    assert call_kw["ContentType"] == "application/json"
    sagemaker_mock.invoke_endpoint_async.assert_called_once()
    assert (
        sagemaker_mock.invoke_endpoint_async.call_args[1]["InputLocation"]
        == "s3://output-bucket/sagemaker-invocation-requests/job-1/0.json"
    )


def test_invoke_sagemaker_endpoint_raises_on_container_error_in_response() -> None:
    """When async response body contains error, RuntimeError is raised."""
    mock_client = MagicMock()
    mock_client.invoke_endpoint_async.return_value = {
        "OutputLocation": "s3://out/resp",
    }
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {"Body": BytesIO(b'{"error":"out of memory"}')}
    with patch("boto3.client", return_value=s3_mock):
        try:
            invoke_sagemaker_endpoint(
                "s3://in/seg.mp4",
                "s3://out/jobs/j1/segments/0.mp4",
                "ep",
                client=mock_client,
            )
        except RuntimeError as e:
            assert "out of memory" in str(e)
            return
    assert False, "expected RuntimeError"
