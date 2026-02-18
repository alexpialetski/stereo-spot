# CloudWatch alarms: alert when any message is in a DLQ (failed-message visibility)
resource "aws_cloudwatch_metric_alarm" "chunking_dlq" {
  alarm_name          = "${local.name}-chunking-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0

  dimensions = {
    QueueName = aws_sqs_queue.chunking_dlq.name
  }

  alarm_description = "Messages in chunking dead-letter queue; investigate failed chunking jobs."
  tags              = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "video_worker_dlq" {
  alarm_name          = "${local.name}-video-worker-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0

  dimensions = {
    QueueName = aws_sqs_queue.video_worker_dlq.name
  }

  alarm_description = "Messages in video-worker dead-letter queue; investigate failed segment processing."
  tags              = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "reassembly_dlq" {
  alarm_name          = "${local.name}-reassembly-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0

  dimensions = {
    QueueName = aws_sqs_queue.reassembly_dlq.name
  }

  alarm_description = "Messages in reassembly dead-letter queue; investigate failed reassembly jobs."
  tags              = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "segment_output_dlq" {
  alarm_name          = "${local.name}-segment-output-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0

  dimensions = {
    QueueName = aws_sqs_queue.segment_output_dlq.name
  }

  alarm_description = "Messages in segment-output dead-letter queue; investigate failed SegmentCompletion writes."
  tags              = local.common_tags
}
