#!/usr/bin/env bash
# Deploy latest stereocrafter-sagemaker image from ECR to the inference EC2 via SSM.
# Requires: inference_backend=http, inference_http_url empty (Terraform-created EC2), and SSM agent on the EC2.
# Usage: deploy-ec2.sh <path-to-env-file>

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

INSTANCE_ID="${INFERENCE_EC2_INSTANCE_ID:-}"
if [[ -z "$INSTANCE_ID" ]]; then
  echo "Error: INFERENCE_EC2_INSTANCE_ID not set. Set inference_backend=http and leave inference_http_url empty, then run terraform-output." >&2
  exit 1
fi

ECR_URL="${ECR_STEREOCRAFTER_SAGEMAKER_URL:?ECR_STEREOCRAFTER_SAGEMAKER_URL not set}"
REGION="${AWS_REGION:-${REGION:-}}"
: "${REGION:?AWS_REGION or REGION must be set (e.g. in .env)}"
IMAGE_TAG="${ECS_IMAGE_TAG:-latest}"
HF_TOKEN_ARN="${HF_TOKEN_SECRET_ARN:-}"
LOG_GROUP="${INFERENCE_EC2_LOG_GROUP:-/ecs/stereo-spot/inference-ec2}"

REGISTRY="${ECR_URL%%/*}"
RUN_CMD="docker run -d --restart unless-stopped --name inference -p 8080:8080 --log-driver awslogs --log-opt awslogs-group=${LOG_GROUP} --log-opt awslogs-region=${REGION} -e AWS_REGION=${REGION} -e HF_TOKEN_ARN=${HF_TOKEN_ARN} ${ECR_URL}:${IMAGE_TAG}"
# SSM RunShellScript expects a list of commands; pass as JSON array
COMMANDS_JSON=$(python3 -c '
import json, sys
cmds = [
    "set -e",
    "docker stop inference 2>/dev/null || true",
    "docker rm inference 2>/dev/null || true",
    "docker image prune -af || true",
    "aws ecr get-login-password --region " + sys.argv[1] + " | docker login --username AWS --password-stdin " + sys.argv[2],
    "docker pull " + sys.argv[3] + ":" + sys.argv[4],
    sys.argv[5],
]
print(json.dumps({"commands": cmds}))
' "$REGION" "$REGISTRY" "$ECR_URL" "$IMAGE_TAG" "$RUN_CMD")

echo "Sending deploy command to instance $INSTANCE_ID..."
CMD_OUT=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "$COMMANDS_JSON" \
  --region "$REGION" \
  --output json)
COMMAND_ID=$(echo "$CMD_OUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Command']['CommandId'])")

echo "Command ID: $COMMAND_ID. Waiting for result..."
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" || true

RESULT=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --output json)
STATUS=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Status',''))")
if [[ "$STATUS" != "Success" ]]; then
  echo "Deploy failed (Status: $STATUS). Command output from instance:" >&2
  echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for key in ('StandardOutputContent', 'StandardErrorContent'):
    val = d.get(key, '').strip()
    if val:
        print(key + ':', file=sys.stderr)
        print(val, file=sys.stderr)
" >&2
  exit 1
fi
echo "Deploy complete. Container restarted with ${ECR_URL}:${IMAGE_TAG}"
