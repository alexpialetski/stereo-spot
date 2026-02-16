#!/usr/bin/env bash
# Deploy the stereocrafter-sagemaker ECR image to the SageMaker endpoint.
# Creates a new model and endpoint config, then updates the endpoint so it pulls the latest image.
#
# Usage: deploy-sagemaker.sh <path-to-env-file>
#   <path-to-env-file>: path to aws-infra .env (from terraform-output). Sourced to get SAGEMAKER_*, ECR_*, REGION, HF_TOKEN_SECRET_ARN.

set -euo pipefail

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

IMAGE_URI="${ECR_STEREOCRAFTER_SAGEMAKER_URL}:latest"
SUFFIX=$(date +%s)
MODEL_NAME="${SAGEMAKER_ENDPOINT_NAME}-${SUFFIX}"
CONFIG_NAME="${SAGEMAKER_ENDPOINT_NAME}-config-${SUFFIX}"

echo "Creating SageMaker model ${MODEL_NAME}..."
aws sagemaker create-model \
  --model-name "$MODEL_NAME" \
  --execution-role-arn "$SAGEMAKER_ENDPOINT_ROLE_ARN" \
  --primary-container "{\"Image\":\"${IMAGE_URI}\",\"Environment\":{\"HF_TOKEN_ARN\":\"${HF_TOKEN_SECRET_ARN}\"}}" \
  --region "$REGION"

echo "Creating endpoint config ${CONFIG_NAME}..."
aws sagemaker create-endpoint-config \
  --endpoint-config-name "$CONFIG_NAME" \
  --production-variants "[{\"VariantName\":\"AllTraffic\",\"ModelName\":\"${MODEL_NAME}\",\"InstanceType\":\"${SAGEMAKER_INSTANCE_TYPE}\",\"InitialInstanceCount\":${SAGEMAKER_INSTANCE_COUNT},\"InitialVariantWeight\":1}]" \
  --region "$REGION"

echo "Updating endpoint ${SAGEMAKER_ENDPOINT_NAME} to use ${CONFIG_NAME}..."
aws sagemaker update-endpoint \
  --endpoint-name "$SAGEMAKER_ENDPOINT_NAME" \
  --endpoint-config-name "$CONFIG_NAME" \
  --region "$REGION"

echo "Deploy started. Check endpoint status: aws sagemaker describe-endpoint --endpoint-name ${SAGEMAKER_ENDPOINT_NAME} --region ${REGION}"
