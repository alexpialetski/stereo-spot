# SageMaker: stereo-inference endpoint. Only when inference_backend=sagemaker.

# --- IAM: SageMaker endpoint execution role ---
data "aws_iam_policy_document" "sagemaker_endpoint_assume" {
  count = var.inference_backend == "sagemaker" ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker_endpoint" {
  count = var.inference_backend == "sagemaker" ? 1 : 0

  name               = "${local.name}-sagemaker-endpoint"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_endpoint_assume[0].json
  tags               = merge(local.common_tags, { Name = "${local.name}-sagemaker-endpoint" })
}

resource "aws_iam_role_policy" "sagemaker_endpoint" {
  count = var.inference_backend == "sagemaker" ? 1 : 0

  name = "sagemaker-endpoint"
  role = aws_iam_role.sagemaker_endpoint[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability"]
        Resource = aws_ecr_repository.inference.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.input.arn, "${aws_s3_bucket.input.arn}/*", aws_s3_bucket.output.arn, "${aws_s3_bucket.output.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.hf_token.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.sagemaker_endpoint[0].arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
      }
    ]
  })
}

# --- SageMaker model (custom container from ECR) ---
locals {
  sagemaker_image = "${aws_ecr_repository.inference.repository_url}:${var.ecs_image_tag}"
}

resource "aws_sagemaker_model" "inference" {
  count = var.inference_backend == "sagemaker" ? 1 : 0

  name               = "${local.name}-inference"
  execution_role_arn = aws_iam_role.sagemaker_endpoint[0].arn

  primary_container {
    image          = local.sagemaker_image
    model_data_url = null
    environment = {
      HF_TOKEN_ARN = aws_secretsmanager_secret.hf_token.arn
    }
  }

  tags = merge(local.common_tags, { Name = "${local.name}-inference" })
}

# --- Endpoint configuration and endpoint (async inference for long-running segments) ---
# Real-time endpoints have a 60s invocation timeout; async allows up to 1 hour.
resource "aws_sagemaker_endpoint_configuration" "inference" {
  count = var.inference_backend == "sagemaker" ? 1 : 0

  name = "${local.name}-inference"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.inference[0].name
    instance_type           = var.sagemaker_instance_type
    initial_instance_count  = var.sagemaker_instance_count
    initial_variant_weight  = 1
  }

  async_inference_config {
    output_config {
      s3_output_path  = "s3://${aws_s3_bucket.output.id}/sagemaker-async-responses/"
      s3_failure_path  = "s3://${aws_s3_bucket.output.id}/sagemaker-async-failures/"
    }
  }

  tags = merge(local.common_tags, { Name = "${local.name}-inference" })
}

resource "aws_sagemaker_endpoint" "inference" {
  count = var.inference_backend == "sagemaker" ? 1 : 0

  name                 = "${local.name}-inference"
  endpoint_config_name  = aws_sagemaker_endpoint_configuration.inference[0].name
  tags                  = merge(local.common_tags, { Name = "${local.name}-inference" })
}

# --- CloudWatch log group for SageMaker endpoint container logs ---
resource "aws_cloudwatch_log_group" "sagemaker_endpoint" {
  count = var.inference_backend == "sagemaker" ? 1 : 0

  name              = "/aws/sagemaker/Endpoints/${local.name}-inference"
  retention_in_days = 7
  tags              = merge(local.common_tags, { Name = "${local.name}-sagemaker-endpoint-logs" })
}
