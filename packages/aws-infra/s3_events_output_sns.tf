# SNS fan-out for output bucket: one topic per (prefix, suffix) so S3 has no overlapping rules.
# Each topic delivers to both output_events and job_status_events (raw message = S3 event JSON).

locals {
  output_sns_topics = {
    "jobs-mp4" = {
      filter_prefix = "jobs/"
      filter_suffix = ".mp4"
    }
    "jobs-reassembly-done" = {
      filter_prefix = "jobs/"
      filter_suffix = ".reassembly-done"
    }
    "sagemaker-responses" = {
      filter_prefix = "sagemaker-async-responses/"
      filter_suffix = null
    }
    "sagemaker-failures" = {
      filter_prefix = "sagemaker-async-failures/"
      filter_suffix = null
    }
  }
}

resource "aws_sns_topic" "output_bucket_event" {
  for_each = local.output_sns_topics

  name = "${local.name}-output-${each.key}"

  tags = { Name = "${local.name}-output-${each.key}" }
}

# S3 can publish to these topics
resource "aws_sns_topic_policy" "output_bucket_event" {
  for_each = local.output_sns_topics

  arn = aws_sns_topic.output_bucket_event[each.key].arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowS3OutputBucketPublish"
        Effect = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action = "sns:Publish"
        Resource = aws_sns_topic.output_bucket_event[each.key].arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_s3_bucket.output.arn
          }
        }
      }
    ]
  })
}

# Each topic delivers to both queues (raw message = same S3 event body as before)
resource "aws_sns_topic_subscription" "output_events" {
  for_each = local.output_sns_topics

  topic_arn             = aws_sns_topic.output_bucket_event[each.key].arn
  protocol              = "sqs"
  endpoint              = aws_sqs_queue.output_events.arn
  raw_message_delivery  = true
}

resource "aws_sns_topic_subscription" "job_status_events" {
  for_each = local.output_sns_topics

  topic_arn             = aws_sns_topic.output_bucket_event[each.key].arn
  protocol              = "sqs"
  endpoint               = aws_sqs_queue.job_status_events.arn
  raw_message_delivery  = true
}

# Allow SNS topics to send to output_events queue
resource "aws_sqs_queue_policy" "output_events_allow_sns" {
  queue_url = aws_sqs_queue.output_events.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      for k, _ in local.output_sns_topics : {
        Sid       = "AllowSnsOutput${replace(k, "-", "_")}SendMessage"
        Effect    = "Allow"
        Principal = { Service = "sns.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.output_events.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.output_bucket_event[k].arn
          }
        }
      }
    ]
  })
}

# Allow SNS topics to send to job_status_events queue
resource "aws_sqs_queue_policy" "job_status_events_allow_sns" {
  queue_url = aws_sqs_queue.job_status_events.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      for k, _ in local.output_sns_topics : {
        Sid       = "AllowSnsOutput${replace(k, "-", "_")}SendMessage"
        Effect    = "Allow"
        Principal = { Service = "sns.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.job_status_events.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.output_bucket_event[k].arn
          }
        }
      }
    ]
  })
}
