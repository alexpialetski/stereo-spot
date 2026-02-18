# S3 event notifications: output bucket → segment-output queue.
# When SageMaker (or inference) writes a segment to jobs/{job_id}/segments/{segment_index}.mp4,
# S3 sends the event here; video-worker consumes and writes SegmentCompletion.

resource "aws_s3_bucket_notification" "output" {
  bucket = aws_s3_bucket.output.id

  queue {
    queue_arn     = aws_sqs_queue.segment_output.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "jobs/"
    filter_suffix = ".mp4"
  }

  depends_on = [aws_sqs_queue_policy.segment_output_allow_s3]
}
