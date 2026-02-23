# EventBridge Pipes: DynamoDB streams (jobs + segment_completions) -> job-events SQS.
# Web-ui consumes raw stream records from the queue, normalizes and runs bridge logic in-process.

resource "aws_iam_role" "job_events_pipes" {
  name               = "${local.name}-job-events-pipes"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = { Service = "pipes.amazonaws.com" }
        Action = "sts:AssumeRole"
      }
    ]
  })
  tags = { Name = "${local.name}-job-events-pipes" }
}

resource "aws_iam_role_policy" "job_events_pipes" {
  name = "job-events-pipes"
  role = aws_iam_role.job_events_pipes.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:DescribeStream", "dynamodb:ListStreams"]
        Resource = [aws_dynamodb_table.jobs.stream_arn, aws_dynamodb_table.segment_completions.stream_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.job_events.arn]
      }
    ]
  })
}

resource "aws_pipes_pipe" "job_events_jobs" {
  name        = "${local.name}-job-events-jobs"
  role_arn    = aws_iam_role.job_events_pipes.arn
  source      = aws_dynamodb_table.jobs.stream_arn
  target      = aws_sqs_queue.job_events.arn
  desired_state = "RUNNING"

  source_parameters {
    dynamodb_stream_parameters {
      starting_position = "LATEST"
      batch_size       = 10
    }
  }

  tags = { Name = "${local.name}-job-events-jobs" }
}

resource "aws_pipes_pipe" "job_events_segment_completions" {
  name        = "${local.name}-job-events-segment-completions"
  role_arn    = aws_iam_role.job_events_pipes.arn
  source      = aws_dynamodb_table.segment_completions.stream_arn
  target      = aws_sqs_queue.job_events.arn
  desired_state = "RUNNING"

  source_parameters {
    dynamodb_stream_parameters {
      starting_position = "LATEST"
      batch_size       = 10
    }
  }

  tags = { Name = "${local.name}-job-events-segment-completions" }
}
