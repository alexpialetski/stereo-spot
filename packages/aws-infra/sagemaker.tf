# SageMaker: StereoCrafter inference endpoint. Video-worker (Fargate) invokes it with S3 URIs.

# --- IAM: SageMaker endpoint execution role ---
data "aws_iam_policy_document" "sagemaker_endpoint_assume" {
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
  name               = "${local.name}-sagemaker-endpoint"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_endpoint_assume.json
  tags               = merge(local.common_tags, { Name = "${local.name}-sagemaker-endpoint" })
}

resource "aws_iam_role_policy" "sagemaker_endpoint" {
  name = "sagemaker-endpoint"
  role = aws_iam_role.sagemaker_endpoint.id
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
        Resource = aws_ecr_repository.stereocrafter_sagemaker.arn
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
      }
    ]
  })
}

# --- SageMaker model (custom container from ECR) ---
locals {
  sagemaker_image = "${aws_ecr_repository.stereocrafter_sagemaker.repository_url}:${var.ecs_image_tag}"
}

resource "aws_sagemaker_model" "stereocrafter" {
  name               = "${local.name}-stereocrafter"
  execution_role_arn = aws_iam_role.sagemaker_endpoint.arn

  primary_container {
    image          = local.sagemaker_image
    model_data_url = null
    environment = {
      HF_TOKEN_ARN = aws_secretsmanager_secret.hf_token.arn
    }
  }

  tags = merge(local.common_tags, { Name = "${local.name}-stereocrafter" })
}

# --- Endpoint configuration and endpoint ---
resource "aws_sagemaker_endpoint_configuration" "stereocrafter" {
  name = "${local.name}-stereocrafter"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.stereocrafter.name
    instance_type           = var.sagemaker_instance_type
    initial_instance_count  = var.sagemaker_instance_count
    initial_variant_weight  = 1
  }

  tags = merge(local.common_tags, { Name = "${local.name}-stereocrafter" })
}

resource "aws_sagemaker_endpoint" "stereocrafter" {
  name                 = "${local.name}-stereocrafter"
  endpoint_config_name  = aws_sagemaker_endpoint_configuration.stereocrafter.name
  tags                  = merge(local.common_tags, { Name = "${local.name}-stereocrafter" })
}
