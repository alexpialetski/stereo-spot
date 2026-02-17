"""
Download StereoCrafter model weights from Hugging Face at container startup.

Reads HF_TOKEN from Secrets Manager via HF_TOKEN_ARN (env), then downloads:
- stabilityai/stable-video-diffusion-img2vid-xt-1-1
- tencent/DepthCrafter
- TencentARC/StereoCrafter

into WEIGHTS_DIR (default /opt/ml/model/weights).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
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


def _secrets_manager_region() -> str | None:
    """Region for Secrets Manager: from AWS_REGION env or parsed from HF_TOKEN_ARN."""
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if region:
        return region
    arn = os.environ.get("HF_TOKEN_ARN")
    if arn and arn.startswith("arn:aws:secretsmanager:"):
        parts = arn.split(":")
        if len(parts) >= 4:
            return parts[3]  # e.g. us-east-1
    return None


def _region_from_secret_arn(arn: str) -> str | None:
    """Parse region from Secrets Manager ARN (arn:aws:secretsmanager:REGION:account:...)."""
    if arn and arn.startswith("arn:aws:secretsmanager:") and arn.count(":") >= 3:
        return arn.split(":")[3]
    return None


def get_hf_token() -> str | None:
    """Retrieve Hugging Face token from AWS Secrets Manager using HF_TOKEN_ARN."""
    arn = os.environ.get("HF_TOKEN_ARN")
    if not arn:
        return None
    try:
        import boto3
        import json

        region = _secrets_manager_region() or _region_from_secret_arn(arn)
        if not region:
            logger.error("Cannot determine region for Secrets Manager (set AWS_REGION or use a full secret ARN)")
            return None
        client = boto3.client("secretsmanager", region_name=region)
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

    # tencent/DepthCrafter has config.json + diffusion_pytorch_model.safetensors at root
    # but no model_index.json; diffusers expects a subfolder per component (not ".").
    depthcrafter_dir = os.path.join(WEIGHTS_DIR, "depthcrafter")
    unet_dir = os.path.join(depthcrafter_dir, "unet")
    if os.path.isdir(depthcrafter_dir):
        config_src = os.path.join(depthcrafter_dir, "config.json")
        weights_src = os.path.join(depthcrafter_dir, "diffusion_pytorch_model.safetensors")
        if os.path.isfile(config_src) and os.path.isfile(weights_src) and not os.path.isfile(
            os.path.join(unet_dir, "config.json")
        ):
            os.makedirs(unet_dir, exist_ok=True)
            shutil.move(config_src, os.path.join(unet_dir, "config.json"))
            shutil.move(weights_src, os.path.join(unet_dir, "diffusion_pytorch_model.safetensors"))
            logger.info("Moved DepthCrafter UNet files into %s", unet_dir)
        model_index_path = os.path.join(depthcrafter_dir, "model_index.json")
        model_index = {
            "_class_name": "DepthCrafterPipeline",
            "unet": ["unet", "DiffusersUNetSpatioTemporalConditionModelDepthCrafter"],
        }
        with open(model_index_path, "w", encoding="utf-8") as f:
            json.dump(model_index, f, indent=2)
        logger.info("Wrote %s for diffusers pipeline loading", model_index_path)

    logger.info("All weights downloaded to %s", WEIGHTS_DIR)
    return True


if __name__ == "__main__":
    ok = download_weights()
    sys.exit(0 if ok or not os.environ.get("HF_TOKEN_ARN") else 1)
