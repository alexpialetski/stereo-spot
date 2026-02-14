# S3 event notifications: input bucket → SQS (no Lambda).
# (1) input/ prefix, .mp4 suffix → chunking queue (user uploads source).
# (2) segments/ prefix, .mp4 suffix → video-worker queue (chunking-worker uploads segments).

resource "aws_s3_bucket_notification" "input" {
  bucket = aws_s3_bucket.input.id

  queue {
    queue_arn     = aws_sqs_queue.chunking.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "input/"
    filter_suffix = ".mp4"
  }

  queue {
    queue_arn     = aws_sqs_queue.video_worker.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "segments/"
    filter_suffix = ".mp4"
  }

  depends_on = [
    aws_sqs_queue_policy.chunking_allow_s3,
    aws_sqs_queue_policy.video_worker_allow_s3,
  ]
}
