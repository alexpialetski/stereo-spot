"""Tests for AWSOperatorLinksProvider and operator_links_from_env."""

import pytest

from stereo_spot_aws_adapters import AWSOperatorLinksProvider, operator_links_from_env


class TestAWSOperatorLinksProvider:
    """Tests for AWSOperatorLinksProvider."""

    def test_get_job_logs_url_contains_job_id_and_region_and_name_prefix(self) -> None:
        provider = AWSOperatorLinksProvider(
            name_prefix="my-app",
            region="eu-west-1",
        )
        url = provider.get_job_logs_url("job-abc-123")
        assert url is not None
        assert "job-abc-123" in url
        assert "eu-west-1" in url
        assert "my-app" in url
        assert "cloudwatch" in url.lower()
        assert "logs-insights" in url or "logsV2" in url

    def test_get_cost_dashboard_url_uses_default_with_app_tag(self) -> None:
        provider = AWSOperatorLinksProvider(
            name_prefix="stereo-spot",
            region="us-east-1",
        )
        url = provider.get_cost_dashboard_url()
        assert url is not None
        assert "costmanagement" in url or "cost-explorer" in url
        assert "stereo-spot" in url

    def test_get_cost_dashboard_url_uses_override_when_set(self) -> None:
        custom = "https://example.com/custom-cost"
        provider = AWSOperatorLinksProvider(
            name_prefix="any",
            region="us-east-1",
            cost_explorer_url=custom,
        )
        assert provider.get_cost_dashboard_url() == custom

    def test_implements_operator_links_provider_protocol(self) -> None:
        from stereo_spot_shared.interfaces import OperatorLinksProvider

        provider = AWSOperatorLinksProvider(name_prefix="x", region="us-east-1")
        assert isinstance(provider, OperatorLinksProvider)


def test_operator_links_from_env_returns_none_when_name_prefix_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NAME_PREFIX", raising=False)
    monkeypatch.delenv("LOGS_REGION", raising=False)
    monkeypatch.delenv("COST_EXPLORER_URL", raising=False)
    assert operator_links_from_env() is None


def test_operator_links_from_env_returns_provider_when_name_prefix_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NAME_PREFIX", "stereo-spot")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("COST_EXPLORER_URL", raising=False)
    provider = operator_links_from_env()
    assert provider is not None
    assert provider.get_job_logs_url("job-1") is not None
    assert "job-1" in provider.get_job_logs_url("job-1")
    assert provider.get_cost_dashboard_url() is not None
