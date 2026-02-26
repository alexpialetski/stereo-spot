# S3 event notifications: output bucket → output-events queue.
# Segment files and final (jobs/*.mp4), reassembly-done sentinel (jobs/*/.reassembly-done),
# SageMaker async responses (sagemaker-async-responses/, sagemaker-async-failures/).

resource "aws_s3_bucket_notification" "output" {
  bucket = aws_s3_bucket.output.id

  queue {
    id            = "segment-files"
    queue_arn     = aws_sqs_queue.output_events.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "jobs/"
    filter_suffix = ".mp4"
  }

  queue {
    id            = "reassembly-done"
    queue_arn     = aws_sqs_queue.output_events.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "jobs/"
    filter_suffix = ".reassembly-done"
  }

  queue {
    id          = "sagemaker-responses"
    queue_arn   = aws_sqs_queue.output_events.arn
    events      = ["s3:ObjectCreated:*"]
    filter_prefix = "sagemaker-async-responses/"
  }

  queue {
    id          = "sagemaker-failures"
    queue_arn   = aws_sqs_queue.output_events.arn
    events      = ["s3:ObjectCreated:*"]
    filter_prefix = "sagemaker-async-failures/"
  }

  # Duplicate events to job-status-events for job-worker (SegmentCompletion, job status, reassembly)
  queue {
    id            = "job-status-segment-files"
    queue_arn     = aws_sqs_queue.job_status_events.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "jobs/"
    filter_suffix = ".mp4"
  }

  queue {
    id            = "job-status-reassembly-done"
    queue_arn     = aws_sqs_queue.job_status_events.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "jobs/"
    filter_suffix = ".reassembly-done"
  }

  queue {
    id            = "job-status-sagemaker-responses"
    queue_arn     = aws_sqs_queue.job_status_events.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "sagemaker-async-responses/"
  }

  queue {
    id            = "job-status-sagemaker-failures"
    queue_arn     = aws_sqs_queue.job_status_events.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "sagemaker-async-failures/"
  }

  depends_on = [aws_sqs_queue_policy.output_events_allow_s3, aws_sqs_queue_policy.job_status_events_allow_s3]
}
