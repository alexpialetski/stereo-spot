# ECR repositories for stereo-spot images. CI pushes web-ui, media-worker, video-worker here.
resource "aws_ecr_repository" "web_ui" {
  name                 = "${local.name}-web-ui"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-web-ui"
  })
}

resource "aws_ecr_repository" "media_worker" {
  name                 = "${local.name}-media-worker"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-media-worker"
  })
}

resource "aws_ecr_repository" "video_worker" {
  name                 = "${local.name}-video-worker"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-video-worker"
  })
}

# SageMaker inference container (StereoCrafter). Push image here; SageMaker model references it.
resource "aws_ecr_repository" "stereocrafter_sagemaker" {
  name                 = "${local.name}-stereocrafter-sagemaker"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-stereocrafter-sagemaker"
  })
}
