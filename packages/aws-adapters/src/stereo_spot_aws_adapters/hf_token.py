"""AWS Secrets Manager Hugging Face token provider."""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


def _region_from_arn(arn: str) -> str | None:
    """Parse region from Secrets Manager ARN (arn:aws:secretsmanager:REGION:...)."""
    if arn and arn.startswith("arn:aws:secretsmanager:") and arn.count(":") >= 3:
        return arn.split(":")[3]
    return None


class AwsSecretsManagerHfTokenProvider:
    """HfTokenProvider that fetches the token from AWS Secrets Manager.
    Reads HF_TOKEN_ARN from env at build time; get_hf_token() uses AWS_REGION or ARN for region."""

    def __init__(self, arn: str | None = None, region: str | None = None) -> None:
        self._arn = arn or os.environ.get("HF_TOKEN_ARN")
        self._region = (
            region
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
        )

    def get_hf_token(self) -> str | None:
        if not self._arn:
            return None
        try:
            import boto3
        except ImportError:
            logger.error("boto3 not installed; cannot fetch HF token from Secrets Manager")
            return None
        region = self._region or _region_from_arn(self._arn)
        if not region:
            logger.error(
                "Cannot determine region for Secrets Manager "
                "(set AWS_REGION or use a full secret ARN)"
            )
            return None
        try:
            client = boto3.client("secretsmanager", region_name=region)
            response = client.get_secret_value(SecretId=self._arn)
            secret = response.get("SecretString")
            if not secret:
                return None
            try:
                data = json.loads(secret)
                if isinstance(data, dict):
                    return (
                        data.get("hf_token")
                        or data.get("HF_TOKEN")
                        or data.get("token")
                    )
                return None
            except json.JSONDecodeError:
                return secret
        except Exception as e:
            logger.error("Failed to fetch HF token from Secrets Manager: %s", e)
            return None
