# Optional inference EC2: when inference_backend=http and inference_http_url is empty.
# Same VPC as ECS so video-worker can call it. Runs the stereocrafter container from ECR.
# AMI: use inference_ec2_ami_id if set, else latest AWS Deep Learning OSS Nvidia GPU AMI (same family as SageMaker GPU).

locals {
  create_inference_ec2 = var.inference_backend == "http" && var.inference_http_url == ""
}

# Default AMI when inference_ec2_ami_id is empty (Deep Learning OSS Nvidia Driver GPU — same family as SageMaker)
data "aws_ami" "inference_ec2_default" {
  count       = local.create_inference_ec2 ? 1 : 0
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["Deep Learning OSS Nvidia Driver AMI GPU*"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}

# IAM role for the inference EC2 (ECR pull, S3, Secrets Manager)
data "aws_iam_policy_document" "inference_ec2_assume" {
  count = local.create_inference_ec2 ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "inference_ec2" {
  count = local.create_inference_ec2 ? 1 : 0

  name               = "${local.name}-inference-ec2"
  assume_role_policy = data.aws_iam_policy_document.inference_ec2_assume[0].json
  tags               = merge(local.common_tags, { Name = "${local.name}-inference-ec2" })
}

resource "aws_iam_role_policy" "inference_ec2" {
  count = local.create_inference_ec2 ? 1 : 0

  name = "inference-ec2"
  role = aws_iam_role.inference_ec2[0].id
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
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
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
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:UpdateInstanceInformation", "ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetEncryptionConfiguration"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "inference_ec2" {
  count = local.create_inference_ec2 ? 1 : 0

  name = "${local.name}-inference-ec2"
  role = aws_iam_role.inference_ec2[0].name
}

# Security group: allow 8080 from VPC (so ECS tasks can call the container)
resource "aws_security_group" "inference_ec2" {
  count = local.create_inference_ec2 ? 1 : 0

  name        = "${local.name}-inference-ec2"
  description = "Inference EC2: allow 8080 from VPC"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [module.vpc.vpc_cidr_block]
    description = "Inference API from ECS tasks"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-inference-ec2" })
}

# User-data: ECR login, pull image, run container (AMI has Docker + NVIDIA driver).
locals {
  inference_ec2_user_data = local.create_inference_ec2 ? templatefile("${path.module}/templates/inference-ec2-userdata.sh", {
    account_id   = data.aws_caller_identity.current.account_id
    ecr_url      = aws_ecr_repository.stereocrafter_sagemaker.repository_url
    image_tag    = var.ecs_image_tag
    region       = local.region
    hf_token_arn = aws_secretsmanager_secret.hf_token.arn
  }) : ""
}

resource "aws_instance" "inference" {
  count = local.create_inference_ec2 ? 1 : 0

  ami                    = var.inference_ec2_ami_id != "" ? var.inference_ec2_ami_id : data.aws_ami.inference_ec2_default[0].id
  instance_type          = "g4dn.xlarge"
  subnet_id              = module.vpc.private_subnets[0]
  vpc_security_group_ids = [aws_security_group.inference_ec2[0].id]
  iam_instance_profile   = aws_iam_instance_profile.inference_ec2[0].name

  user_data = local.inference_ec2_user_data

  tags = merge(local.common_tags, {
    Name = "${local.name}-inference-ec2"
  })
}
