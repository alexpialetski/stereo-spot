# ECS cluster and services: web-ui (Fargate + ALB), media-worker (Fargate + scaling), video-worker (EC2 GPU + scaling).

# --- ECS cluster ---
resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  tags = { Name = local.name }
}

# --- IAM: task execution role (pull images, write logs) ---
data "aws_iam_policy_document" "ecs_task_execution_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${local.name}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_execution_assume.json
  tags               = { Name = "${local.name}-ecs-task-execution" }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# --- IAM: task roles (same permissions as prior IRSA) ---
data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Web UI: S3 (input, output), DynamoDB Jobs
resource "aws_iam_role" "web_ui_task" {
  name               = "${local.name}-web-ui-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
  tags               = { Name = "${local.name}-web-ui-task" }
}

resource "aws_iam_role_policy" "web_ui_task" {
  name = "web-ui"
  role = aws_iam_role.web_ui_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
          Resource = [aws_s3_bucket.input.arn, "${aws_s3_bucket.input.arn}/*", aws_s3_bucket.output.arn, "${aws_s3_bucket.output.arn}/*"]
        },
        {
          Effect   = "Allow"
          Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:BatchGetItem"]
          Resource = [aws_dynamodb_table.jobs.arn, "${aws_dynamodb_table.jobs.arn}/index/*"]
        },
        {
          Effect   = "Allow"
          Action   = ["dynamodb:GetItem", "dynamodb:Query"]
          Resource = [aws_dynamodb_table.segment_completions.arn]
        },
        {
          Effect   = "Allow"
          Action   = ["sqs:SendMessage"]
          Resource = [aws_sqs_queue.deletion.arn]
        }
      ],
      var.enable_youtube_ingest ? [{
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.ingest[0].arn]
      }] : []
    )
  })
}

# Media worker: S3, DynamoDB (Jobs, SegmentCompletions, ReassemblyTriggered), SQS chunking + reassembly + deletion + ingest
resource "aws_iam_role" "media_worker_task" {
  name               = "${local.name}-media-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
  tags               = { Name = "${local.name}-media-worker-task" }
}

resource "aws_iam_role_policy" "media_worker_task" {
  name = "media-worker"
  role = aws_iam_role.media_worker_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
          Resource = [aws_s3_bucket.input.arn, "${aws_s3_bucket.input.arn}/*", aws_s3_bucket.output.arn, "${aws_s3_bucket.output.arn}/*"]
        },
        {
          Effect   = "Allow"
          Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:ConditionCheckItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"]
          Resource = [aws_dynamodb_table.jobs.arn, "${aws_dynamodb_table.jobs.arn}/index/*", aws_dynamodb_table.segment_completions.arn, aws_dynamodb_table.reassembly_triggered.arn]
        },
        {
          Effect   = "Allow"
          Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
          Resource = concat(
            [aws_sqs_queue.chunking.arn, aws_sqs_queue.reassembly.arn, aws_sqs_queue.deletion.arn],
            var.enable_youtube_ingest ? [aws_sqs_queue.ingest[0].arn] : []
          )
        }
      ],
      var.enable_youtube_ingest ? [{
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.ytdlp_cookies[0].arn]
      }] : []
    )
  })
}

# Video worker: S3, DynamoDB SegmentCompletions, SQS video-worker, SageMaker InvokeEndpoint
resource "aws_iam_role" "video_worker_task" {
  name               = "${local.name}-video-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
  tags               = { Name = "${local.name}-video-worker-task" }
}

resource "aws_iam_role_policy" "video_worker_task" {
  name = "video-worker"
  role = aws_iam_role.video_worker_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
          Resource = [aws_s3_bucket.input.arn, "${aws_s3_bucket.input.arn}/*", aws_s3_bucket.output.arn, "${aws_s3_bucket.output.arn}/*"]
        },
        {
          Effect   = "Allow"
          Action   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
          Resource = [aws_dynamodb_table.segment_completions.arn]
        },
        {
          Effect   = "Allow"
          Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
          Resource = [aws_dynamodb_table.jobs.arn]
        },
        {
          Effect   = "Allow"
          Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
          Resource = [aws_sqs_queue.video_worker.arn, aws_sqs_queue.output_events.arn]
        },
        {
          Effect   = "Allow"
          Action   = ["dynamodb:PutItem"]
          Resource = aws_dynamodb_table.reassembly_triggered.arn
        },
        {
          Effect   = "Allow"
          Action   = ["sqs:SendMessage"]
          Resource = aws_sqs_queue.reassembly.arn
        }
      ],
      var.inference_backend == "sagemaker" ? [
        {
          Effect   = "Allow"
          Action   = ["sagemaker:InvokeEndpoint", "sagemaker:InvokeEndpointAsync"]
          Resource = [aws_sagemaker_endpoint.inference[0].arn]
        },
        {
          Effect   = "Allow"
          Action   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem"]
          Resource = [aws_dynamodb_table.inference_invocations.arn]
        }
      ] : []
    )
  })
}

# --- Security groups ---
resource "aws_security_group" "web_ui_alb" {
  name        = "${local.name}-web-ui-alb"
  description = "ALB for web-ui"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-web-ui-alb" }
}

resource "aws_security_group" "web_ui_tasks" {
  name        = "${local.name}-web-ui-tasks"
  description = "Web UI ECS tasks"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.web_ui_alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-web-ui-tasks" }
}

# Shared security group for Fargate tasks (media-worker; no ALB)
resource "aws_security_group" "fargate_tasks" {
  name        = "${local.name}-fargate-tasks"
  description = "Fargate ECS tasks (media-worker)"
  vpc_id      = module.vpc.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-fargate-tasks" }
}

# --- ALB and target group ---
resource "aws_lb" "web_ui" {
  name               = "${local.name}-web-ui"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.web_ui_alb.id]
  subnets            = module.vpc.public_subnets
  idle_timeout       = 600 # 10 min so long-running SSE /jobs/{id}/events stream is not closed

  tags = { Name = "${local.name}-web-ui" }
}

resource "aws_lb_target_group" "web_ui" {
  name        = "${local.name}-web-ui"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = module.vpc.vpc_id
  target_type = "ip"

  health_check {
    path                = "/"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
  }

  tags = { Name = "${local.name}-web-ui" }
}

resource "aws_lb_listener" "web_ui" {
  load_balancer_arn = aws_lb.web_ui.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web_ui.arn
  }
}

# --- Task definitions ---
locals {
  web_ui_image       = "${aws_ecr_repository.web_ui.repository_url}:${var.ecs_image_tag}"
  media_worker_image = "${aws_ecr_repository.media_worker.repository_url}:${var.ecs_image_tag}"
  video_worker_image = "${aws_ecr_repository.video_worker.repository_url}:${var.ecs_image_tag}"
  ecs_env_common = [
    { name = "AWS_REGION", value = local.region }
  ]
  web_ui_env = concat(
    local.ecs_env_common,
    [
      { name = "INPUT_BUCKET_NAME", value = aws_s3_bucket.input.id },
      { name = "OUTPUT_BUCKET_NAME", value = aws_s3_bucket.output.id },
      { name = "JOBS_TABLE_NAME", value = aws_dynamodb_table.jobs.name },
      { name = "SEGMENT_COMPLETIONS_TABLE_NAME", value = aws_dynamodb_table.segment_completions.name },
      { name = "DELETION_QUEUE_URL", value = aws_sqs_queue.deletion.url },
      { name = "NAME_PREFIX", value = var.name_prefix }
    ],
    var.enable_youtube_ingest ? [{ name = "INGEST_QUEUE_URL", value = aws_sqs_queue.ingest[0].url }] : []
  )
  media_worker_env = concat(
    local.ecs_env_common,
    [
      { name = "INPUT_BUCKET_NAME", value = aws_s3_bucket.input.id },
      { name = "OUTPUT_BUCKET_NAME", value = aws_s3_bucket.output.id },
      { name = "JOBS_TABLE_NAME", value = aws_dynamodb_table.jobs.name },
      { name = "SEGMENT_COMPLETIONS_TABLE_NAME", value = aws_dynamodb_table.segment_completions.name },
      { name = "REASSEMBLY_TRIGGERED_TABLE_NAME", value = aws_dynamodb_table.reassembly_triggered.name },
      { name = "CHUNKING_QUEUE_URL", value = aws_sqs_queue.chunking.url },
      { name = "REASSEMBLY_QUEUE_URL", value = aws_sqs_queue.reassembly.url },
      { name = "DELETION_QUEUE_URL", value = aws_sqs_queue.deletion.url }
    ],
    var.enable_youtube_ingest ? [
      { name = "INGEST_QUEUE_URL", value = aws_sqs_queue.ingest[0].url },
      { name = "YTDLP_COOKIES_SECRET_ARN", value = aws_secretsmanager_secret.ytdlp_cookies[0].arn }
    ] : []
  )
  inference_http_url = var.inference_backend == "http" ? var.inference_http_url : ""
  video_worker_inference_env = var.inference_backend == "sagemaker" ? [
    { name = "INFERENCE_BACKEND", value = "sagemaker" },
    { name = "SAGEMAKER_ENDPOINT_NAME", value = aws_sagemaker_endpoint.inference[0].name },
    { name = "SAGEMAKER_REGION", value = local.region },
    { name = "INFERENCE_MAX_IN_FLIGHT", value = tostring(var.sagemaker_instance_count) },
    { name = "INFERENCE_INVOCATIONS_TABLE_NAME", value = aws_dynamodb_table.inference_invocations.name }
  ] : [
    { name = "INFERENCE_BACKEND", value = "http" },
    { name = "INFERENCE_HTTP_URL", value = local.inference_http_url }
  ]
  video_worker_env = concat(local.ecs_env_common, [
    { name = "INPUT_BUCKET_NAME", value = aws_s3_bucket.input.id },
    { name = "OUTPUT_BUCKET_NAME", value = aws_s3_bucket.output.id },
    { name = "JOBS_TABLE_NAME", value = aws_dynamodb_table.jobs.name },
    { name = "SEGMENT_COMPLETIONS_TABLE_NAME", value = aws_dynamodb_table.segment_completions.name },
    { name = "VIDEO_WORKER_QUEUE_URL", value = aws_sqs_queue.video_worker.url },
    { name = "OUTPUT_EVENTS_QUEUE_URL", value = aws_sqs_queue.output_events.url },
    { name = "REASSEMBLY_TRIGGERED_TABLE_NAME", value = aws_dynamodb_table.reassembly_triggered.name },
    { name = "REASSEMBLY_QUEUE_URL", value = aws_sqs_queue.reassembly.url },
  ], local.video_worker_inference_env)
}

resource "aws_ecs_task_definition" "web_ui" {
  family                   = "web-ui"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_web_ui_cpu
  memory                   = var.ecs_web_ui_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.web_ui_task.arn

  container_definitions = jsonencode([{
    name      = "web-ui"
    image     = local.web_ui_image
    essential = true
    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]
    environment = local.web_ui_env
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/${local.name}/web-ui"
        "awslogs-region"        = local.region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "media_worker" {
  family                   = "media-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_media_worker_cpu
  memory                   = var.ecs_media_worker_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.media_worker_task.arn

  container_definitions = jsonencode([{
    name        = "media-worker"
    image       = local.media_worker_image
    essential   = true
    environment = local.media_worker_env
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/${local.name}/media-worker"
        "awslogs-region"        = local.region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

# Video-worker runs on Fargate (thin client); inference is on SageMaker.
resource "aws_ecs_task_definition" "video_worker" {
  family                   = "video-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_video_worker_cpu
  memory                   = var.ecs_video_worker_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.video_worker_task.arn

  container_definitions = jsonencode([{
    name        = "video-worker"
    image       = local.video_worker_image
    essential   = true
    environment = local.video_worker_env
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/${local.name}/video-worker"
        "awslogs-region"        = local.region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

# --- CloudWatch log groups for ECS ---
resource "aws_cloudwatch_log_group" "web_ui" {
  name              = "/ecs/${local.name}/web-ui"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "media_worker" {
  name              = "/ecs/${local.name}/media-worker"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "video_worker" {
  name              = "/ecs/${local.name}/video-worker"
  retention_in_days = 7
}

# --- ECS services ---
resource "aws_ecs_service" "web_ui" {
  name            = "web-ui"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web_ui.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.web_ui_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web_ui.arn
    container_name   = "web-ui"
    container_port   = 8000
  }
}

resource "aws_ecs_service" "media_worker" {
  name            = "media-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.media_worker.arn
  desired_count   = 0
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.fargate_tasks.id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# Video-worker: Fargate (thin client; inference on SageMaker).
resource "aws_ecs_service" "video_worker" {
  name            = "video-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.video_worker.arn
  desired_count   = 0
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.fargate_tasks.id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# --- Application Auto Scaling: video-worker (scale on video-worker queue depth) ---
resource "aws_appautoscaling_target" "video_worker" {
  max_capacity       = var.ecs_video_worker_max_capacity
  min_capacity       = var.ecs_video_worker_min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.video_worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "video_worker_sqs" {
  name               = "${local.name}-video-worker-sqs"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.video_worker.resource_id
  scalable_dimension = aws_appautoscaling_target.video_worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.video_worker.service_namespace

  target_tracking_scaling_policy_configuration {
    customized_metric_specification {
      dimensions {
        name  = "QueueName"
        value = aws_sqs_queue.video_worker.name
      }
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      statistic   = "Sum"
    }
    target_value       = 10.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# --- Application Auto Scaling: media-worker (scale on chunking queue depth) ---
resource "aws_appautoscaling_target" "media_worker" {
  max_capacity       = 10
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.media_worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "media_worker_sqs" {
  name               = "${local.name}-media-worker-sqs"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.media_worker.resource_id
  scalable_dimension = aws_appautoscaling_target.media_worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.media_worker.service_namespace

  target_tracking_scaling_policy_configuration {
    customized_metric_specification {
      dimensions {
        name  = "QueueName"
        value = aws_sqs_queue.chunking.name
      }
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      statistic   = "Sum"
    }
    target_value       = 10.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
