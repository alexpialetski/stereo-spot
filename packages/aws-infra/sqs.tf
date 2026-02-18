# Dead-letter queues (one per main queue)
resource "aws_sqs_queue" "chunking_dlq" {
  name = "${local.name}-chunking-dlq"

  tags = merge(local.common_tags, {
    Name = "${local.name}-chunking-dlq"
  })
}

resource "aws_sqs_queue" "video_worker_dlq" {
  name = "${local.name}-video-worker-dlq"

  tags = merge(local.common_tags, {
    Name = "${local.name}-video-worker-dlq"
  })
}

resource "aws_sqs_queue" "reassembly_dlq" {
  name = "${local.name}-reassembly-dlq"

  tags = merge(local.common_tags, {
    Name = "${local.name}-reassembly-dlq"
  })
}

resource "aws_sqs_queue" "segment_output_dlq" {
  name = "${local.name}-segment-output-dlq"

  tags = merge(local.common_tags, {
    Name = "${local.name}-segment-output-dlq"
  })
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

  tags = merge(local.common_tags, {
    Name = "${local.name}-chunking"
  })
}

resource "aws_sqs_queue" "video_worker" {
  name                       = "${local.name}-video-worker"
  visibility_timeout_seconds = 600 # 10 min; worker only invokes async then polls for response, not full inference
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.video_worker_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = merge(local.common_tags, {
    Name = "${local.name}-video-worker"
  })
}

resource "aws_sqs_queue" "reassembly" {
  name                       = "${local.name}-reassembly"
  visibility_timeout_seconds = 600 # 10 min
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.reassembly_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = merge(local.common_tags, {
    Name = "${local.name}-reassembly"
  })
}

resource "aws_sqs_queue" "segment_output" {
  name                       = "${local.name}-segment-output"
  visibility_timeout_seconds = 120 # 2 min; processing is one DynamoDB put
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.segment_output_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })

  tags = merge(local.common_tags, {
    Name = "${local.name}-segment-output"
  })
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

# Allow S3 output bucket to send events to segment-output queue (prefix jobs/, suffix .mp4)
resource "aws_sqs_queue_policy" "segment_output_allow_s3" {
  queue_url = aws_sqs_queue.segment_output.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3OutputBucketSendMessage"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.segment_output.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_s3_bucket.output.arn
          }
        }
      }
    ]
  })
}
