output "region" {
  description = "AWS region"
  value       = local.region
}

output "name_prefix" {
  description = "Prefix for resource names (e.g. stereo-spot); used by web-ui for operator links (Cost, Open logs)"
  value       = var.name_prefix
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

output "output_events_queue_url" {
  description = "URL of the output-events SQS queue (output bucket: segment files and SageMaker async responses)"
  value       = aws_sqs_queue.output_events.url
}

output "job_status_events_queue_url" {
  description = "URL of the job-status-events SQS queue (duplicate output bucket events for job-worker)"
  value       = aws_sqs_queue.job_status_events.url
}

output "deletion_queue_url" {
  description = "URL of the deletion SQS queue (job removal cleanup)"
  value       = aws_sqs_queue.deletion.url
}

output "ingest_queue_url" {
  description = "URL of the ingest SQS queue (URL / YouTube source jobs); null when enable_youtube_ingest is false"
  value       = local.enable_youtube_ingest ? aws_sqs_queue.ingest[0].url : null
}

output "job_events_queue_url" {
  description = "URL of the job-events SQS queue (Pipes feed stream records; web-ui consumes and does normalization + SSE + Web Push)"
  value       = aws_sqs_queue.job_events.url
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

output "inference_invocations_table_name" {
  description = "Name of the DynamoDB InferenceInvocations table (SageMaker output_location -> job/segment)"
  value       = aws_dynamodb_table.inference_invocations.name
}

output "push_subscriptions_table_name" {
  description = "Name of the DynamoDB Push subscriptions table (Web Push subscription payloads)"
  value       = aws_dynamodb_table.push_subscriptions.name
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
  description = "ALB DNS name for web-ui"
  value       = aws_lb.web_ui.dns_name
}

output "web_ui_url" {
  description = "Web UI URL (HTTPS when certs at project root, else HTTP); used for Web Push notification links and WEB_UI_URL in ECS"
  value       = local.alb_url
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

output "ecr_job_worker_url" {
  description = "ECR repository URL for job-worker image"
  value       = aws_ecr_repository.job_worker.repository_url
}

output "ecr_inference_url" {
  description = "ECR repository URL for stereo-inference image"
  value       = aws_ecr_repository.inference.repository_url
}

# --- SageMaker (only when inference_backend=sagemaker) ---

output "sagemaker_endpoint_name" {
  description = "SageMaker endpoint name (for video-worker SAGEMAKER_ENDPOINT_NAME)"
  value       = var.inference_backend == "sagemaker" ? aws_sagemaker_endpoint.inference[0].name : null
}

output "sagemaker_endpoint_role_arn" {
  description = "IAM role ARN for SageMaker endpoint (for stereo-inference:inference-redeploy)"
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

output "sagemaker_iw3_video_codec" {
  description = "iw3 video codec for SageMaker model (for stereo-inference:inference-redeploy)"
  value       = var.sagemaker_iw3_video_codec
}

# --- HTTP inference (only when inference_backend=http) ---

output "inference_http_url" {
  description = "URL for HTTP inference backend (video-worker INFERENCE_HTTP_URL); set via variable when inference_backend=http"
  value       = var.inference_backend == "http" ? var.inference_http_url : null
}

output "hf_token_secret_arn" {
  description = "ARN of the Secrets Manager secret for Hugging Face token (set value manually)"
  value       = aws_secretsmanager_secret.hf_token.arn
}

output "ytdlp_cookies_secret_arn" {
  description = "ARN of the Secrets Manager secret for yt-dlp cookies (set via root update-ytdlp-cookies target)"
  value       = aws_secretsmanager_secret.ytdlp_cookies.arn
}

output "vapid_secret_arn" {
  description = "ARN of the Secrets Manager secret for VAPID Web Push keys (set via deploy-vapid-to-secrets-manager)"
  value       = aws_secretsmanager_secret.vapid.arn
}

# --- CodeBuild ---

output "codebuild_project_name" {
  description = "Name of the CodeBuild project for stereo-inference (for nx run stereo-inference:inference-build)"
  value       = aws_codebuild_project.inference.name
}
