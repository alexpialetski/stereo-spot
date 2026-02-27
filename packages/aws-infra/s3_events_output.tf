# S3 event notifications: output bucket → SNS topics (one per filter); SNS fans out to output-events and job-status-events.
# Avoids S3 rule "overlapping prefixes/suffixes" by having each (prefix, suffix) sent to a single topic; see s3_events_output_sns.tf.

resource "aws_s3_bucket_notification" "output" {
  bucket = aws_s3_bucket.output.id

  topic {
    id            = "jobs-mp4"
    topic_arn     = aws_sns_topic.output_bucket_event["jobs-mp4"].arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "jobs/"
    filter_suffix = ".mp4"
  }

  topic {
    id            = "jobs-reassembly-done"
    topic_arn     = aws_sns_topic.output_bucket_event["jobs-reassembly-done"].arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "jobs/"
    filter_suffix = ".reassembly-done"
  }

  topic {
    id          = "sagemaker-responses"
    topic_arn   = aws_sns_topic.output_bucket_event["sagemaker-responses"].arn
    events      = ["s3:ObjectCreated:*"]
    filter_prefix = "sagemaker-async-responses/"
  }

  topic {
    id          = "sagemaker-failures"
    topic_arn   = aws_sns_topic.output_bucket_event["sagemaker-failures"].arn
    events      = ["s3:ObjectCreated:*"]
    filter_prefix = "sagemaker-async-failures/"
  }

  depends_on = [
    aws_sns_topic_policy.output_bucket_event,
    aws_sqs_queue_policy.output_events_allow_sns,
    aws_sqs_queue_policy.job_status_events_allow_sns,
  ]
}
