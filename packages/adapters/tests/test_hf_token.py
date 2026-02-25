"""Tests for hf_token_provider_from_env: provider selection (aws vs no-op)."""

from __future__ import annotations

from unittest.mock import patch

from stereo_spot_aws_adapters.hf_token import AwsSecretsManagerHfTokenProvider
from stereo_spot_shared import NoOpHfTokenProvider

from stereo_spot_adapters.env_config import hf_token_provider_from_env


def test_aws_returns_secrets_manager_provider() -> None:
    with patch.dict("os.environ", {"PLATFORM": "aws"}, clear=False):
        provider = hf_token_provider_from_env()
    assert isinstance(provider, AwsSecretsManagerHfTokenProvider)


def test_gcp_returns_no_op() -> None:
    with patch.dict("os.environ", {"PLATFORM": "gcp"}, clear=False):
        provider = hf_token_provider_from_env()
    assert isinstance(provider, NoOpHfTokenProvider)
    assert provider.get_hf_token() is None


def test_default_platform_aws_returns_aws_provider() -> None:
    with patch.dict("os.environ", {}, clear=False):
        if "PLATFORM" in __import__("os").environ:
            del __import__("os").environ["PLATFORM"]
        provider = hf_token_provider_from_env()
    assert isinstance(provider, AwsSecretsManagerHfTokenProvider)
