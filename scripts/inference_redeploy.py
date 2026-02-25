#!/usr/bin/env python3
"""Redeploy inference image to the platform endpoint (PLATFORM=aws → SageMaker).

Clones the current endpoint config (from Terraform or a previous deploy), swaps in the new
model (latest ECR image), creates a new endpoint config, and updates the endpoint.
This avoids drift: async config and production variant settings stay as-is.
"""

import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from env_helpers import WORKSPACE_ROOT, get_platform, infra_env_path, load_env


def _redeploy_sagemaker() -> None:
    env_path = infra_env_path("aws")
    if not env_path.exists():
        print(
            f"Error: Env file not found: {env_path}. Run: nx run aws-infra:terraform-output",
            file=sys.stderr,
        )
        sys.exit(1)
    infra = load_env(env_path)

    endpoint_name = infra.get("SAGEMAKER_ENDPOINT_NAME")
    ecr_url = infra.get("ECR_INFERENCE_URL")
    region = infra.get("REGION") or infra.get("AWS_REGION") or "us-east-1"
    role_arn = infra.get("SAGEMAKER_ENDPOINT_ROLE_ARN")
    hf_secret_arn = infra.get("HF_TOKEN_SECRET_ARN") or ""
    iw3_codec = infra.get("SAGEMAKER_IW3_VIDEO_CODEC") or "libx264"

    for key, val in (
        ("SAGEMAKER_ENDPOINT_NAME", endpoint_name),
        ("ECR_INFERENCE_URL", ecr_url),
        ("SAGEMAKER_ENDPOINT_ROLE_ARN", role_arn),
    ):
        if not val:
            print(f"Error: {key} not set in {env_path}. Run: nx run aws-infra:terraform-output", file=sys.stderr)
            sys.exit(1)

    import boto3

    client = boto3.client("sagemaker", region_name=region)
    image_uri = f"{ecr_url.rstrip('/')}:latest"
    suffix = int(time.time())
    model_name = f"{endpoint_name}-{suffix}"
    config_name = f"{endpoint_name}-config-{suffix}"

    print(f"Reading current endpoint config for {endpoint_name}...")
    ep = client.describe_endpoint(EndpointName=endpoint_name)
    current_config_name = ep["EndpointConfigName"]
    config = client.describe_endpoint_config(EndpointConfigName=current_config_name)

    # New production variants: same as current but with new model name
    production_variants = []
    for pv in config["ProductionVariants"]:
        production_variants.append({
            "VariantName": pv["VariantName"],
            "ModelName": model_name,
            "InstanceType": pv["InstanceType"],
            "InitialInstanceCount": pv["InitialInstanceCount"],
            "InitialVariantWeight": pv.get("InitialVariantWeight", 1),
        })

    # Async inference config: use current as-is
    async_config = config.get("AsyncInferenceConfig")
    if not async_config:
        print("Error: Current endpoint config has no AsyncInferenceConfig.", file=sys.stderr)
        sys.exit(1)

    # Model environment: match Terraform (sagemaker.tf)
    env = {
        "PLATFORM": "aws",
        "HF_TOKEN_ARN": hf_secret_arn,
        "IW3_VIDEO_CODEC": iw3_codec,
    }
    if iw3_codec == "h264_nvenc":
        env["NVIDIA_DRIVER_CAPABILITIES"] = "all"

    print(f"Creating SageMaker model {model_name} (IW3_VIDEO_CODEC={iw3_codec})...")
    client.create_model(
        ModelName=model_name,
        ExecutionRoleArn=role_arn,
        PrimaryContainer={"Image": image_uri, "Environment": env},
    )

    print(f"Creating endpoint config {config_name} (clone of {current_config_name}, new model)...")
    client.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=production_variants,
        AsyncInferenceConfig=async_config,
    )

    print(f"Updating endpoint {endpoint_name} to use {config_name}...")
    client.update_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)

    print(
        f"Deploy started. Check endpoint status: "
        f"aws sagemaker describe-endpoint --endpoint-name {endpoint_name} --region {region}"
    )


def _run_gcp() -> None:
    print("Error: GCP inference redeploy is not implemented yet.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    platform = get_platform()
    if platform == "aws":
        _redeploy_sagemaker()
    elif platform == "gcp":
        _run_gcp()
    else:
        print(f"Error: Unsupported PLATFORM={platform}.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
