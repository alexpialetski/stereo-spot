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
  visibility_timeout_seconds = 1800 # 20 min for GPU segment processing
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
