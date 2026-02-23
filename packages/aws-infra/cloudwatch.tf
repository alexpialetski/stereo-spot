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
}

resource "aws_cloudwatch_metric_alarm" "output_events_dlq" {
  alarm_name          = "${local.name}-output-events-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0

  dimensions = {
    QueueName = aws_sqs_queue.output_events_dlq.name
  }

  alarm_description = "Messages in output-events dead-letter queue; investigate failed output-event processing."
}

resource "aws_cloudwatch_metric_alarm" "job_events_dlq" {
  alarm_name          = "${local.name}-job-events-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0

  dimensions = {
    QueueName = aws_sqs_queue.job_events_dlq.name
  }

  alarm_description = "Messages in job-events DLQ; investigate failed job-events processing (Pipes -> web-ui)."
}
