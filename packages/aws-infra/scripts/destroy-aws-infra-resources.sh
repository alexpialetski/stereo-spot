#!/usr/bin/env bash
#
# Destroy all AWS resources that would be managed by the aws-infra Terraform
# module. Use this when Terraform state is lost (e.g. backend bucket was
# destroyed) and you need to tear down the resources via AWS CLI.
#
# Prerequisites: AWS CLI configured with credentials that can delete these
#   resources. Optional: set NAME_PREFIX (default stereo-spot), REGION (default us-east-1).
#
# Usage: ./scripts/destroy-aws-infra-resources.sh
#        NAME_PREFIX=myapp REGION=eu-west-1 ./scripts/destroy-aws-infra-resources.sh
#
# Order: CloudWatch alarms → SQS queues (main, then DLQs) → S3 lifecycle + empty + delete buckets → DynamoDB tables.

set -euo pipefail

NAME_PREFIX="${NAME_PREFIX:-stereo-spot}"
REGION="${REGION:-us-east-1}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
INPUT_BUCKET="${NAME_PREFIX}-input-${ACCOUNT_ID}"
OUTPUT_BUCKET="${NAME_PREFIX}-output-${ACCOUNT_ID}"

echo "Using NAME_PREFIX=${NAME_PREFIX} REGION=${REGION} ACCOUNT_ID=${ACCOUNT_ID}"
echo "Input bucket: ${INPUT_BUCKET}"
echo "Output bucket: ${OUTPUT_BUCKET}"
echo "Press Enter to continue or Ctrl+C to abort..."
read -r

# 1. CloudWatch alarms (3)
echo "Deleting CloudWatch alarms..."
aws cloudwatch delete-alarms --region "${REGION}" \
  --alarm-names \
  "${NAME_PREFIX}-chunking-dlq-messages" \
  "${NAME_PREFIX}-video-worker-dlq-messages" \
  "${NAME_PREFIX}-reassembly-dlq-messages" 2>/dev/null || true

# 2. SQS queues: main queues first (6)
echo "Deleting SQS queues..."
for name in "${NAME_PREFIX}-chunking" "${NAME_PREFIX}-video-worker" "${NAME_PREFIX}-reassembly" \
            "${NAME_PREFIX}-chunking-dlq" "${NAME_PREFIX}-video-worker-dlq" "${NAME_PREFIX}-reassembly-dlq"; do
  url="https://sqs.${REGION}.amazonaws.com/${ACCOUNT_ID}/${name}"
  aws sqs delete-queue --region "${REGION}" --queue-url "${url}" 2>/dev/null || true
done

# 3. S3: remove lifecycle config from output bucket, then empty both buckets, then delete
echo "Removing S3 lifecycle configuration from output bucket..."
aws s3api delete-bucket-lifecycle --bucket "${OUTPUT_BUCKET}" --region "${REGION}" 2>/dev/null || true

echo "Emptying S3 buckets..."
for bucket in "${INPUT_BUCKET}" "${OUTPUT_BUCKET}"; do
  aws s3 rm "s3://${bucket}/" --recursive --region "${REGION}" 2>/dev/null || true
done

echo "Deleting S3 buckets..."
aws s3 rb "s3://${INPUT_BUCKET}" --force --region "${REGION}" 2>/dev/null || true
aws s3 rb "s3://${OUTPUT_BUCKET}" --force --region "${REGION}" 2>/dev/null || true

# 4. DynamoDB tables (3)
echo "Deleting DynamoDB tables..."
aws dynamodb delete-table --region "${REGION}" --table-name "${NAME_PREFIX}-jobs" 2>/dev/null || true
aws dynamodb delete-table --region "${REGION}" --table-name "${NAME_PREFIX}-segment-completions" 2>/dev/null || true
aws dynamodb delete-table --region "${REGION}" --table-name "${NAME_PREFIX}-reassembly-triggered" 2>/dev/null || true

echo "Done. 17 resources (3 alarms, 6 SQS queues, 2 S3 buckets + lifecycle, 3 DynamoDB tables) targeted for deletion."
