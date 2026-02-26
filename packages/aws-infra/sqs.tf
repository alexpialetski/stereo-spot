# Dead-letter queues (one per main queue)
resource "aws_sqs_queue" "chunking_dlq" {
  name = "${local.name}-chunking-dlq"

  tags = { Name = "${local.name}-chunking-dlq" }
}

resource "aws_sqs_queue" "video_worker_dlq" {
  name = "${local.name}-video-worker-dlq"

  tags = { Name = "${local.name}-video-worker-dlq" }
}

resource "aws_sqs_queue" "reassembly_dlq" {
  name = "${local.name}-reassembly-dlq"

  tags = { Name = "${local.name}-reassembly-dlq" }
}

resource "aws_sqs_queue" "output_events_dlq" {
  name = "${local.name}-output-events-dlq"

  tags = { Name = "${local.name}-output-events-dlq" }
}

resource "aws_sqs_queue" "deletion_dlq" {
  name = "${local.name}-deletion-dlq"

  tags = { Name = "${local.name}-deletion-dlq" }
}

resource "aws_sqs_queue" "ingest_dlq" {
  count = local.enable_youtube_ingest ? 1 : 0

  name = "${local.name}-ingest-dlq"

  tags = { Name = "${local.name}-ingest-dlq" }
}

resource "aws_sqs_queue" "job_events_dlq" {
  name = "${local.name}-job-events-dlq"

  tags = { Name = "${local.name}-job-events-dlq" }
}

resource "aws_sqs_queue" "job_status_events_dlq" {
  name = "${local.name}-job-status-events-dlq"

  tags = { Name = "${local.name}-job-status-events-dlq" }
}

# Main queues with redrive to DLQ
resource "aws_sqs_queue" "chunking" {
  name                       = "${local.name}-chunking"
  visibility_timeout_seconds = 900     # 15 min for chunking
  message_retention_seconds  = 1209600 # 14 days
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.chunking_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = { Name = "${local.name}-chunking" }
}

resource "aws_sqs_queue" "video_worker" {
  name                       = "${local.name}-video-worker"
  visibility_timeout_seconds = 2400 # 40 min; keep message hidden while in-flight (2× max segment duration)
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.video_worker_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = { Name = "${local.name}-video-worker" }
}

resource "aws_sqs_queue" "reassembly" {
  name                       = "${local.name}-reassembly"
  visibility_timeout_seconds = 3600 # 1 h; download + concat + upload of large segments can exceed 10 min
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.reassembly_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = { Name = "${local.name}-reassembly" }
}

resource "aws_sqs_queue" "output_events" {
  name                       = "${local.name}-output-events"
  visibility_timeout_seconds = 120 # 2 min; processing is one DynamoDB put
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.output_events_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = { Name = "${local.name}-output-events" }
}

resource "aws_sqs_queue" "deletion" {
  name                       = "${local.name}-deletion"
  visibility_timeout_seconds = 600 # 10 min for S3 + DynamoDB cleanup
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.deletion_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = { Name = "${local.name}-deletion" }
}

resource "aws_sqs_queue" "ingest" {
  count = local.enable_youtube_ingest ? 1 : 0

  name                       = "${local.name}-ingest"
  visibility_timeout_seconds = 1200 # 20 min for URL download
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq[0].arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = { Name = "${local.name}-ingest" }
}

resource "aws_sqs_queue" "job_events" {
  name                       = "${local.name}-job-events"
  visibility_timeout_seconds = 60 # 1 min; web-ui consumes quickly
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.job_events_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = { Name = "${local.name}-job-events" }
}

resource "aws_sqs_queue" "job_status_events" {
  name                       = "${local.name}-job-status-events"
  visibility_timeout_seconds = 120 # 2 min; job-worker does DynamoDB put + reassembly trigger
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.job_status_events_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = { Name = "${local.name}-job-status-events" }
}

# Allow S3 input bucket to send events to chunking queue (prefix input/, suffix .mp4)
resource "aws_sqs_queue_policy" "chunking_allow_s3" {
  queue_url = aws_sqs_queue.chunking.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3InputBucketSendMessage"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.chunking.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_s3_bucket.input.arn
          }
        }
      }
    ]
  })
}

# Allow S3 input bucket to send events to video-worker queue (prefix segments/, suffix .mp4)
resource "aws_sqs_queue_policy" "video_worker_allow_s3" {
  queue_url = aws_sqs_queue.video_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3InputBucketSendMessage"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.video_worker.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_s3_bucket.input.arn
          }
        }
      }
    ]
  })
}

# Allow S3 output bucket to send events to output-events queue (segment files and SageMaker async responses)
resource "aws_sqs_queue_policy" "output_events_allow_s3" {
  queue_url = aws_sqs_queue.output_events.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3OutputBucketSendMessage"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.output_events.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_s3_bucket.output.arn
          }
        }
      }
    ]
  })
}

# Allow S3 output bucket to send events to job-status-events queue (duplicate of output-events for job-worker)
resource "aws_sqs_queue_policy" "job_status_events_allow_s3" {
  queue_url = aws_sqs_queue.job_status_events.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3OutputBucketSendMessage"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.job_status_events.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_s3_bucket.output.arn
          }
        }
      }
    ]
  })
}

# Allow web-ui task role to send to ingest queue (URL / YouTube jobs)
resource "aws_sqs_queue_policy" "ingest_allow_web_ui" {
  count = local.enable_youtube_ingest ? 1 : 0

  queue_url = aws_sqs_queue.ingest[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowWebUiSendMessage"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.web_ui_task.arn
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.ingest[0].arn
      }
    ]
  })
}
