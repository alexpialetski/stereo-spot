"""
Download StereoCrafter model weights from Hugging Face at container startup.

Reads HF_TOKEN from Secrets Manager via HF_TOKEN_ARN (env), then downloads:
- stabilityai/stable-video-diffusion-img2vid-xt-1-1
- tencent/DepthCrafter
- TencentARC/StereoCrafter

into WEIGHTS_DIR (default /opt/ml/model/weights).
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

WEIGHTS_DIR = os.environ.get("WEIGHTS_DIR", "/opt/ml/model/weights")
REPOS = [
    "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
    "tencent/DepthCrafter",
    "TencentARC/StereoCrafter",
]


def get_hf_token() -> str | None:
    """Retrieve Hugging Face token from AWS Secrets Manager using HF_TOKEN_ARN."""
    arn = os.environ.get("HF_TOKEN_ARN")
    if not arn:
        return None
    try:
        import boto3
        import json

        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=arn)
        secret = response.get("SecretString")
        if not secret:
            return None
        try:
            data = json.loads(secret)
            if isinstance(data, dict):
                return data.get("hf_token") or data.get("HF_TOKEN") or data.get("token")
            return None
        except json.JSONDecodeError:
            return secret  # Plain string token
    except Exception as e:
        logger.error("Failed to fetch HF token from Secrets Manager: %s", e)
        return None


def download_weights() -> bool:
    """Download all model repos to WEIGHTS_DIR. Returns True on success."""
    token = get_hf_token()
    if not token:
        logger.warning("HF_TOKEN_ARN not set or token unavailable; skipping weight download")
        return False

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        logger.error("huggingface_hub not installed; cannot download weights")
        return False

    os.makedirs(WEIGHTS_DIR, exist_ok=True)
    for repo_id in REPOS:
        local_dir = os.path.join(WEIGHTS_DIR, repo_id.split("/")[-1].lower())
        logger.info("Downloading %s -> %s", repo_id, local_dir)
        try:
            snapshot_download(
                repo_id=repo_id,
                local_dir=local_dir,
                token=token,
                local_dir_use_symlinks=False,
            )
            logger.info("Downloaded %s", repo_id)
        except Exception as e:
            logger.exception("Failed to download %s: %s", repo_id, e)
            return False
    logger.info("All weights downloaded to %s", WEIGHTS_DIR)
    return True


if __name__ == "__main__":
    ok = download_weights()
    sys.exit(0 if ok or not os.environ.get("HF_TOKEN_ARN") else 1)
