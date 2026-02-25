"""Tests for platform facade: _platform() and _require_aws()."""

import os

import pytest

from stereo_spot_adapters.env_config import _platform, _require_aws


def test_platform_default_is_aws() -> None:
    """Without PLATFORM set, _platform() returns 'aws'."""
    os.environ.pop("PLATFORM", None)
    assert _platform() == "aws"


def test_platform_strips_and_lowercases() -> None:
    """PLATFORM is stripped and lowercased."""
    os.environ["PLATFORM"] = "  AWS  "
    try:
        assert _platform() == "aws"
    finally:
        os.environ.pop("PLATFORM", None)


def test_require_aws_raises_for_gcp() -> None:
    """_require_aws() raises NotImplementedError when PLATFORM=gcp."""
    os.environ["PLATFORM"] = "gcp"
    try:
        with pytest.raises(NotImplementedError, match="not implemented.*only aws"):
            _require_aws()
    finally:
        os.environ.pop("PLATFORM", None)
