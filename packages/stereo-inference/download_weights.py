"""
Download StereoCrafter model weights from Hugging Face at container startup.

Uses HfTokenProvider from adapters (e.g. AWS Secrets Manager when PLATFORM=aws).
If HF_TOKEN_ARN is set, token is read from the configured cloud secret store.
Downloads:
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

from stereo_spot_shared import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

WEIGHTS_DIR = os.environ.get("WEIGHTS_DIR", "/opt/ml/model/weights")
REPOS = [
    "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
    "tencent/DepthCrafter",
    "TencentARC/StereoCrafter",
]


def get_hf_token() -> str | None:
    """Return Hugging Face token from platform adapter (e.g. Secrets Manager when PLATFORM=aws)."""
    from stereo_spot_adapters.env_config import hf_token_provider_from_env
    provider = hf_token_provider_from_env()
    return provider.get_hf_token()


def download_weights() -> bool:
    """Download all model repos to WEIGHTS_DIR. Returns True on success."""
    token = get_hf_token()
    if not token:
        logger.warning(
            "HF token not available (set HF_TOKEN_ARN when using AWS); skipping weight download"
        )
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
    # Exit 1 only when download failed and token was expected (HF_TOKEN_ARN set).
    sys.exit(0 if ok or not os.environ.get("HF_TOKEN_ARN") else 1)
