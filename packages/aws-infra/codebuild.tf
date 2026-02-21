# CodeBuild: Build and push stereo-inference Docker image to ECR.
# Source: clone from public repo (no CodeStar connection). Trigger manually via deploy target.

# --- IAM: CodeBuild service role ---
data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codebuild_inference" {
  name               = "${local.name}-codebuild-inference"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
  tags               = { Name = "${local.name}-codebuild-inference" }
}

resource "aws_iam_role_policy" "codebuild_inference" {
  name = "codebuild-inference"
  role = aws_iam_role.codebuild_inference.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/codebuild/*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = aws_ecr_repository.inference.arn
      }
    ]
  })
}

# --- CodeBuild project ---
resource "aws_codebuild_project" "inference" {
  name          = "${local.name}-inference-build"
  description   = "Build and push stereo-inference Docker image to ECR"
  service_role  = aws_iam_role.codebuild_inference.arn
  build_timeout = 60 # minutes for large Docker build

  source {
    type      = "NO_SOURCE"
    buildspec = <<-BUILDSPEC
      version: 0.2
      env:
        variables:
          ECR_URI: "${aws_ecr_repository.inference.repository_url}:${var.ecs_image_tag}"
          REPO_URL: "${var.codebuild_inference_repo_url}"
          DOCKER_BUILD_EXTRA_ARGS: ""
      phases:
        build:
          commands:
            - echo "Cloning repository..."
            - git clone --depth 1 $REPO_URL src && cd src
            - echo "Logging in to ECR..."
            - aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin ${local.account_id}.dkr.ecr.${local.region}.amazonaws.com
            # - echo "Pulling previous image for cache (ignore failure on first build)..."
            # - docker pull $ECR_URI || true
            - echo "Building Docker image..."
            - docker build $${DOCKER_BUILD_EXTRA_ARGS} --cache-from $ECR_URI -f packages/stereo-inference/Dockerfile -t $ECR_URI .
            - echo "Pushing to ECR..."
            - docker push $ECR_URI
      BUILDSPEC
  }

  environment {
    type                        = "LINUX_CONTAINER"
    image                       = "aws/codebuild/standard:7.0"
    compute_type                = "BUILD_GENERAL1_LARGE"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true # Required for Docker build
  }

  artifacts {
    type = "NO_ARTIFACTS"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = "/aws/codebuild/${local.name}-inference-build"
      stream_name = "build"
    }
  }

  tags = { Name = "${local.name}-inference-build" }
}
