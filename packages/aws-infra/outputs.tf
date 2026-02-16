output "region" {
  description = "AWS region"
  value       = local.region
}

output "input_bucket_name" {
  description = "Name of the S3 input bucket (source uploads, segment files)"
  value       = aws_s3_bucket.input.id
}

output "output_bucket_name" {
  description = "Name of the S3 output bucket (segment outputs, final.mp4)"
  value       = aws_s3_bucket.output.id
}

output "chunking_queue_url" {
  description = "URL of the chunking SQS queue"
  value       = aws_sqs_queue.chunking.url
}

output "video_worker_queue_url" {
  description = "URL of the video-worker SQS queue"
  value       = aws_sqs_queue.video_worker.url
}

output "reassembly_queue_url" {
  description = "URL of the reassembly SQS queue"
  value       = aws_sqs_queue.reassembly.url
}

output "jobs_table_name" {
  description = "Name of the DynamoDB Jobs table"
  value       = aws_dynamodb_table.jobs.name
}

output "segment_completions_table_name" {
  description = "Name of the DynamoDB SegmentCompletions table"
  value       = aws_dynamodb_table.segment_completions.name
}

output "reassembly_triggered_table_name" {
  description = "Name of the DynamoDB ReassemblyTriggered table"
  value       = aws_dynamodb_table.reassembly_triggered.name
}

# --- ECS / ECR ---

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.main.arn
}

output "web_ui_alb_dns_name" {
  description = "ALB DNS name for web-ui (HTTP)"
  value       = aws_lb.web_ui.dns_name
}

output "web_ui_url" {
  description = "Web UI URL (http://ALB DNS)"
  value       = "http://${aws_lb.web_ui.dns_name}"
}

output "ecr_web_ui_url" {
  description = "ECR repository URL for web-ui image"
  value       = aws_ecr_repository.web_ui.repository_url
}

output "ecr_media_worker_url" {
  description = "ECR repository URL for media-worker image"
  value       = aws_ecr_repository.media_worker.repository_url
}

output "ecr_video_worker_url" {
  description = "ECR repository URL for video-worker image"
  value       = aws_ecr_repository.video_worker.repository_url
}

output "ecr_stereocrafter_sagemaker_url" {
  description = "ECR repository URL for SageMaker inference (StereoCrafter) image"
  value       = aws_ecr_repository.stereocrafter_sagemaker.repository_url
}

# --- SageMaker (only when inference_backend=sagemaker) ---

output "sagemaker_endpoint_name" {
  description = "SageMaker endpoint name (for video-worker SAGEMAKER_ENDPOINT_NAME)"
  value       = var.inference_backend == "sagemaker" ? aws_sagemaker_endpoint.stereocrafter[0].name : null
}

output "sagemaker_endpoint_role_arn" {
  description = "IAM role ARN for SageMaker endpoint (for stereocrafter-sagemaker:sagemaker-deploy)"
  value       = var.inference_backend == "sagemaker" ? aws_iam_role.sagemaker_endpoint[0].arn : null
}

output "sagemaker_instance_type" {
  description = "SageMaker endpoint instance type (e.g. ml.g4dn.xlarge)"
  value       = var.sagemaker_instance_type
}

output "sagemaker_instance_count" {
  description = "SageMaker endpoint instance count"
  value       = var.sagemaker_instance_count
}

# --- Inference EC2 (only when inference_backend=http and inference_ec2_enabled=true) ---

output "inference_http_url" {
  description = "URL for HTTP inference backend (video-worker INFERENCE_HTTP_URL)"
  value       = var.inference_backend == "http" && length(aws_instance.inference) > 0 ? "http://${aws_instance.inference[0].private_ip}:8080" : null
}

output "inference_ec2_private_ip" {
  description = "Private IP of the inference EC2 (for SSH or stereocrafter-ec2-deploy)"
  value       = var.inference_backend == "http" && length(aws_instance.inference) > 0 ? aws_instance.inference[0].private_ip : null
}

output "inference_ec2_instance_id" {
  description = "Instance ID of the inference EC2 (for SSM deploy)"
  value       = var.inference_backend == "http" && length(aws_instance.inference) > 0 ? aws_instance.inference[0].id : null
}

output "hf_token_secret_arn" {
  description = "ARN of the Secrets Manager secret for Hugging Face token (set value manually)"
  value       = aws_secretsmanager_secret.hf_token.arn
}

# --- CodeBuild ---

output "codebuild_project_name" {
  description = "Name of the CodeBuild project for stereocrafter-sagemaker (for nx run stereocrafter-sagemaker:sagemaker-build)"
  value       = aws_codebuild_project.stereocrafter.name
}
