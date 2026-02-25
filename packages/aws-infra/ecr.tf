# ECR repositories for stereo-spot images. CI pushes web-ui, media-worker, video-worker here.
resource "aws_ecr_repository" "web_ui" {
  name                 = "${local.name}-web-ui"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "${local.name}-web-ui" }
}

resource "aws_ecr_repository" "media_worker" {
  name                 = "${local.name}-media-worker"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "${local.name}-media-worker" }
}

resource "aws_ecr_repository" "video_worker" {
  name                 = "${local.name}-video-worker"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "${local.name}-video-worker" }
}

# Stereo-inference container. Push image here; SageMaker model references it.
resource "aws_ecr_repository" "inference" {
  name                 = "${local.name}-inference"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "${local.name}-inference" }
}

# Bootstrap: build and push a SageMaker-compliant stub image so the endpoint reaches InService on first apply.
# Stub implements GET /ping and POST /invocations on 8080. Replace with real image via inference-build then inference-redeploy.
# Requires Docker and AWS CLI where Terraform runs (from packages/aws-infra). Runs only on create.
resource "null_resource" "inference_ecr_bootstrap" {
  count = var.inference_backend == "sagemaker" ? 1 : 0

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      TAG="${aws_ecr_repository.inference.repository_url}:${var.ecs_image_tag}"
      REGISTRY="${regex("^[^/]+", aws_ecr_repository.inference.repository_url)}"
      aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin "$REGISTRY"
      docker build -t "$TAG" -f sagemaker-stub/Dockerfile sagemaker-stub
      docker push "$TAG"
    EOT
    working_dir = path.module
  }

  depends_on = [aws_ecr_repository.inference]
}
