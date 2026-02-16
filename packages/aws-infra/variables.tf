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

# --- Inference backend: SageMaker vs HTTP (e.g. EC2 for dev) ---

variable "inference_backend" {
  description = "Inference backend: sagemaker (managed endpoint) or http (e.g. EC2 running same container)"
  type        = string
  default     = "http"

  validation {
    condition     = contains(["sagemaker", "http"], var.inference_backend)
    error_message = "inference_backend must be sagemaker or http."
  }
}

variable "inference_http_url" {
  description = "When inference_backend=http, URL of your inference server to use instead of Terraform-created EC2 (e.g. http://10.0.1.5:8080). Leave empty to have Terraform create the inference EC2."
  type        = string
  default     = ""
}

variable "inference_ec2_ami_id" {
  description = "When inference_backend=http and inference_http_url is empty, AMI for the GPU EC2. Empty = use latest AWS Deep Learning OSS Nvidia Driver GPU AMI (same family as typical SageMaker GPU runtimes)."
  type        = string
  default     = ""
}

variable "inference_ec2_instance_type" {
  description = "Instance type for the inference EC2. Use g4dn.xlarge (or similar GPU) for real inference; use t3.medium when your org SCP denies GPU instances (pipeline works but inference is CPU-only/slow)."
  type        = string
  default     = "t3.medium"
}

# --- SageMaker (StereoCrafter endpoint; only when inference_backend=sagemaker) ---

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

# --- CodeBuild (stereocrafter-sagemaker image) ---

variable "codebuild_stereocrafter_repo_url" {
  description = "Git repository URL to clone for stereocrafter-sagemaker build (e.g. https://github.com/user/stereo-spot.git)"
  type        = string
  default     = "https://github.com/alexpialetski/stereo-spot.git"
}
