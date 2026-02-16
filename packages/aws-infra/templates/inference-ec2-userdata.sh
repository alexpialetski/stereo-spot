#!/bin/bash
# Bootstrap inference EC2: ECR login, pull stereocrafter image, run container with CloudWatch Logs.
# Requires Docker and NVIDIA container runtime on the AMI (e.g. Deep Learning AMI).
set -e
REGISTRY="${account_id}.dkr.ecr.${region}.amazonaws.com"
aws ecr get-login-password --region "${region}" | docker login --username AWS --password-stdin "$REGISTRY"
docker pull ${ecr_url}:${image_tag}
# Stop any existing container so we run the latest image
docker stop inference 2>/dev/null || true
docker rm inference 2>/dev/null || true
docker run -d --restart unless-stopped --name inference -p 8080:8080 \
  --log-driver awslogs \
  --log-opt awslogs-group="${log_group}" \
  --log-opt awslogs-region="${region}" \
  -e AWS_REGION="${region}" \
  -e HF_TOKEN_ARN="${hf_token_arn}" \
  ${ecr_url}:${image_tag}
