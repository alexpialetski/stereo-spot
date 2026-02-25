"""Tests for AWS Secrets Manager HF token provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from stereo_spot_aws_adapters.hf_token import (
    AwsSecretsManagerHfTokenProvider,
    _region_from_arn,
)


def test_region_from_arn() -> None:
    assert _region_from_arn("arn:aws:secretsmanager:us-east-1:123456789:secret:name") == "us-east-1"
    assert _region_from_arn("arn:aws:secretsmanager:eu-west-1:000:secret:x") == "eu-west-1"
    assert _region_from_arn("") is None
    assert _region_from_arn("not-an-arn") is None
    assert _region_from_arn("arn:aws:other:us-east-1:x") is None


def test_get_hf_token_returns_none_when_no_arn() -> None:
    provider = AwsSecretsManagerHfTokenProvider(arn=None)
    assert provider.get_hf_token() is None


def test_get_hf_token_fetches_from_secrets_manager() -> None:
    provider = AwsSecretsManagerHfTokenProvider(
        arn="arn:aws:secretsmanager:us-east-1:123:secret:hf",
        region="us-east-1",
    )
    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": '{"hf_token": "my-token"}'}
    with patch("boto3.client", return_value=mock_client):
        assert provider.get_hf_token() == "my-token"
    mock_client.get_secret_value.assert_called_once_with(SecretId=provider._arn)


def test_get_hf_token_accepts_plain_string_secret() -> None:
    provider = AwsSecretsManagerHfTokenProvider(
        arn="arn:aws:secretsmanager:us-east-1:123:secret:hf",
        region="us-east-1",
    )
    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": "plain-token"}
    with patch("boto3.client", return_value=mock_client):
        assert provider.get_hf_token() == "plain-token"


def test_get_hf_token_prefers_hf_token_key() -> None:
    provider = AwsSecretsManagerHfTokenProvider(
        arn="arn:aws:secretsmanager:us-east-1:123:secret:hf",
        region="us-east-1",
    )
    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {
        "SecretString": '{"HF_TOKEN": "upper", "hf_token": "lower", "token": "t"}'
    }
    with patch("boto3.client", return_value=mock_client):
        assert provider.get_hf_token() == "lower"
