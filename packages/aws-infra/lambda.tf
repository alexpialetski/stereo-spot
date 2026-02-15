# Reassembly trigger Lambda: DynamoDB Stream (SegmentCompletions) -> conditional create
# ReassemblyTriggered -> send job_id to reassembly queue.
# Build the deployment zip first: nx run reassembly-trigger:build

variable "lambda_reassembly_trigger_zip_path" {
  description = "Path to the reassembly-trigger Lambda deployment zip (build with: nx run reassembly-trigger:build)"
  type        = string
  default     = ""
}

locals {
  # Default path relative to this Terraform module (packages/aws-infra)
  reassembly_trigger_zip = var.lambda_reassembly_trigger_zip_path != "" ? var.lambda_reassembly_trigger_zip_path : "${path.module}/../reassembly-trigger/dist/deploy.zip"
}

# IAM role for Lambda execution
resource "aws_iam_role" "reassembly_trigger_lambda" {
  name = "${local.name}-reassembly-trigger-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name}-reassembly-trigger-lambda"
  })
}

# Policy: CloudWatch Logs, DynamoDB (Jobs get, SegmentCompletions query, ReassemblyTriggered put),
# DynamoDB Stream (read), SQS send to reassembly queue
resource "aws_iam_role_policy" "reassembly_trigger_lambda" {
  name = "reassembly-trigger-lambda"
  role = aws_iam_role.reassembly_trigger_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem"
        ]
        Resource = aws_dynamodb_table.jobs.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query"
        ]
        Resource = "${aws_dynamodb_table.segment_completions.arn}/index/*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.segment_completions.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.reassembly_triggered.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
          "dynamodb:DescribeStream",
          "dynamodb:ListStreams"
        ]
        Resource = aws_dynamodb_table.segment_completions.stream_arn
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage"
        ]
        Resource = aws_sqs_queue.reassembly.arn
      }
    ]
  })
}

# Lambda function (only created if zip exists, so apply can succeed without building first)
resource "aws_lambda_function" "reassembly_trigger" {
  count = fileexists(local.reassembly_trigger_zip) ? 1 : 0

  function_name    = "${local.name}-reassembly-trigger"
  role             = aws_iam_role.reassembly_trigger_lambda.arn
  handler          = "reassembly_trigger.handler.lambda_handler"
  runtime          = "python3.12"
  filename         = local.reassembly_trigger_zip
  source_code_hash = fileexists(local.reassembly_trigger_zip) ? filebase64sha256(local.reassembly_trigger_zip) : null

  timeout     = 30
  memory_size = 256

  environment {
    variables = {
      JOBS_TABLE_NAME                 = aws_dynamodb_table.jobs.name
      SEGMENT_COMPLETIONS_TABLE_NAME  = aws_dynamodb_table.segment_completions.name
      REASSEMBLY_TRIGGERED_TABLE_NAME = aws_dynamodb_table.reassembly_triggered.name
      REASSEMBLY_QUEUE_URL            = aws_sqs_queue.reassembly.url
    }
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-reassembly-trigger"
  })
}

# Event source: SegmentCompletions stream -> Lambda
resource "aws_lambda_event_source_mapping" "segment_completions_stream" {
  count = fileexists(local.reassembly_trigger_zip) ? 1 : 0

  event_source_arn  = aws_dynamodb_table.segment_completions.stream_arn
  function_name     = aws_lambda_function.reassembly_trigger[0].function_name
  starting_position = "LATEST"
  batch_size        = 100
}
