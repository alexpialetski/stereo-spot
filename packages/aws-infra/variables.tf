variable "region" {
  description = "AWS region to deploy resources (override via TF_VAR_region, e.g. from .env)"
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for resource names (e.g. stereo-spot)"
  type        = string
  default     = "stereo-spot"
}

variable "dlq_max_receive_count" {
  description = "Max receive count before message is sent to DLQ (per queue)"
  type        = number
  default     = 5
}

# --- ECS compute ---

variable "ecs_image_tag" {
  description = "Docker image tag for ECS task definitions (web-ui, media-worker, video-worker)"
  type        = string
  default     = "latest"
}

variable "ecs_web_ui_cpu" {
  description = "CPU units for web-ui Fargate task (1024 = 1 vCPU)"
  type        = number
  default     = 256
}

variable "ecs_web_ui_memory" {
  description = "Memory (MiB) for web-ui Fargate task"
  type        = number
  default     = 512
}

variable "ecs_media_worker_cpu" {
  description = "CPU units for media-worker Fargate task"
  type        = number
  default     = 512
}

variable "ecs_media_worker_memory" {
  description = "Memory (MiB) for media-worker Fargate task"
  type        = number
  default     = 1024
}

variable "ecs_video_worker_cpu" {
  description = "CPU units for video-worker Fargate task (thin client; inference on SageMaker)"
  type        = number
  default     = 512
}

variable "ecs_video_worker_memory" {
  description = "Memory (MiB) for video-worker Fargate task"
  type        = number
  default     = 1024
}

variable "ecs_video_worker_min_capacity" {
  description = "Minimum number of video-worker tasks (1 = one task always running)"
  type        = number
  default     = 1
}

variable "ecs_video_worker_max_capacity" {
  description = "Maximum number of video-worker tasks"
  type        = number
  default     = 8
}

# --- SageMaker (StereoCrafter endpoint) ---

variable "sagemaker_instance_type" {
  description = "SageMaker endpoint instance type (GPU, e.g. ml.g4dn.xlarge)"
  type        = string
  default     = "ml.g4dn.xlarge"
}

variable "sagemaker_instance_count" {
  description = "Number of instances for the SageMaker endpoint"
  type        = number
  default     = 1
}
