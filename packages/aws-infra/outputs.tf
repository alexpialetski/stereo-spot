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
