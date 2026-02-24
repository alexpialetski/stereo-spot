#!/usr/bin/env bash
# Deploy the stereo-inference ECR image to the SageMaker endpoint.
# Clones the current endpoint config (from Terraform or a previous deploy), swaps in the new
# model (latest ECR image), creates a new endpoint config, and updates the endpoint.
# This avoids drift: async config (e.g. MaxConcurrentInvocationsPerInstance) and production
# variant settings (instance type, count) stay whatever the endpoint currently uses.
#
# Usage: deploy-sagemaker.sh <path-to-env-file>
#   <path-to-env-file>: path to aws-infra .env (from terraform-output). Sourced for
#   SAGEMAKER_ENDPOINT_NAME, ECR_INFERENCE_URL, REGION, SAGEMAKER_ENDPOINT_ROLE_ARN,
#   SAGEMAKER_IW3_VIDEO_CODEC, HF_TOKEN_SECRET_ARN.

set -euo pipefail

if ! command -v jq &>/dev/null; then
  echo "Error: jq is required. Install jq (e.g. apt install jq / brew install jq)." >&2
  exit 1
fi
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <path-to-env-file>" >&2
  echo "  e.g. $0 packages/aws-infra/.env" >&2
  exit 1
fi
ENV_FILE="$1"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: env file not found: $ENV_FILE. Run: nx run aws-infra:terraform-output" >&2
  exit 1
fi
# shellcheck source=/dev/null
. "$ENV_FILE"

IMAGE_URI="${ECR_INFERENCE_URL}:latest"
SUFFIX=$(date +%s)
MODEL_NAME="${SAGEMAKER_ENDPOINT_NAME}-${SUFFIX}"
CONFIG_NAME="${SAGEMAKER_ENDPOINT_NAME}-config-${SUFFIX}"

echo "Reading current endpoint config for ${SAGEMAKER_ENDPOINT_NAME}..."
CURRENT_CONFIG_NAME=$(aws sagemaker describe-endpoint \
  --endpoint-name "$SAGEMAKER_ENDPOINT_NAME" \
  --region "$REGION" \
  --query 'EndpointConfigName' \
  --output text)
CONFIG_JSON=$(aws sagemaker describe-endpoint-config \
  --endpoint-config-name "$CURRENT_CONFIG_NAME" \
  --region "$REGION" \
  --output json)

# New production variants: same as current but with new model name.
PRODUCTION_VARIANTS_JSON=$(echo "$CONFIG_JSON" | jq -c --arg model "$MODEL_NAME" \
  '[.ProductionVariants[] | {VariantName, ModelName: $model, InstanceType, InitialInstanceCount, InitialVariantWeight}]')
# Async inference config: use current config as-is (OutputConfig, ClientConfig, etc.).
ASYNC_CONFIG_JSON=$(echo "$CONFIG_JSON" | jq -c '.AsyncInferenceConfig')

# Model environment: match Terraform (sagemaker.tf). IW3_VIDEO_CODEC from .env (terraform-output).
IW3_VIDEO_CODEC="${SAGEMAKER_IW3_VIDEO_CODEC:-libx264}"
ENV_JSON=$(jq -n \
  --arg hf "$HF_TOKEN_SECRET_ARN" \
  --arg codec "$IW3_VIDEO_CODEC" \
  '{HF_TOKEN_ARN: $hf, IW3_VIDEO_CODEC: $codec} + (if $codec == "h264_nvenc" then {NVIDIA_DRIVER_CAPABILITIES: "all"} else {} end)')
PRIMARY_CONTAINER=$(jq -n --arg image "$IMAGE_URI" --argjson env "$ENV_JSON" '{Image: $image, Environment: $env}')

echo "Creating SageMaker model ${MODEL_NAME} (IW3_VIDEO_CODEC=${IW3_VIDEO_CODEC})..."
aws sagemaker create-model \
  --model-name "$MODEL_NAME" \
  --execution-role-arn "$SAGEMAKER_ENDPOINT_ROLE_ARN" \
  --primary-container "$PRIMARY_CONTAINER" \
  --region "$REGION"

echo "Creating endpoint config ${CONFIG_NAME} (clone of ${CURRENT_CONFIG_NAME}, new model)..."
aws sagemaker create-endpoint-config \
  --endpoint-config-name "$CONFIG_NAME" \
  --production-variants "$PRODUCTION_VARIANTS_JSON" \
  --async-inference-config "$ASYNC_CONFIG_JSON" \
  --region "$REGION"

echo "Updating endpoint ${SAGEMAKER_ENDPOINT_NAME} to use ${CONFIG_NAME}..."
aws sagemaker update-endpoint \
  --endpoint-name "$SAGEMAKER_ENDPOINT_NAME" \
  --endpoint-config-name "$CONFIG_NAME" \
  --region "$REGION"

echo "Deploy started. Check endpoint status: aws sagemaker describe-endpoint --endpoint-name ${SAGEMAKER_ENDPOINT_NAME} --region ${REGION}"
