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

# --- SageMaker ---

output "sagemaker_endpoint_name" {
  description = "SageMaker endpoint name (for video-worker SAGEMAKER_ENDPOINT_NAME)"
  value       = aws_sagemaker_endpoint.stereocrafter.name
}

output "hf_token_secret_arn" {
  description = "ARN of the Secrets Manager secret for Hugging Face token (set value manually)"
  value       = aws_secretsmanager_secret.hf_token.arn
}

# --- CodeBuild ---

output "codebuild_project_name" {
  description = "Name of the CodeBuild project for stereocrafter-sagemaker (for nx run stereocrafter-sagemaker:deploy)"
  value       = aws_codebuild_project.stereocrafter.name
}
