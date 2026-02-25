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

# Feature flags: set via root .env (TF_VAR_*) or CLI. Scripts at repo root can update root .env.

variable "enable_youtube_ingest" {
  description = "Enable YouTube URL ingest (ingest queue and ytdlp-cookies secret). Secret value is set out-of-band via root script."
  type        = bool
  default     = false
}

variable "load_balancer_certificate_id" {
  description = "When set, enable load balancer HTTPS listener and HTTP→HTTPS redirect. On AWS this is the ACM certificate ARN. Set by root update-alb-certificates script. Empty = HTTP only."
  type        = string
  default     = ""
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
  default     = "sagemaker"

  validation {
    condition     = contains(["sagemaker", "http"], var.inference_backend)
    error_message = "inference_backend must be sagemaker or http."
  }
}

variable "inference_http_url" {
  description = "When inference_backend=http, URL of your inference server (e.g. http://10.0.1.5:8080). You must run the inference service yourself (e.g. SageMaker, or your own EC2/container)."
  type        = string
  default     = ""
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
  default     = 2
}

variable "sagemaker_iw3_video_codec" {
  description = "iw3 video codec: libx264 (software) or h264_nvenc (GPU). Image builds FFmpeg with NVENC 11.1 for ml.g4dn (driver 470)."
  type        = string
  default     = "h264_nvenc"
  validation {
    condition     = contains(["libx264", "h264_nvenc"], var.sagemaker_iw3_video_codec)
    error_message = "sagemaker_iw3_video_codec must be libx264 or h264_nvenc."
  }
}

# --- CodeBuild (stereo-inference image) ---

variable "codebuild_inference_repo_url" {
  description = "Git repository URL to clone for stereo-inference build (e.g. https://github.com/user/stereo-spot.git)"
  type        = string
  default     = "https://github.com/alexpialetski/stereo-spot.git"
}
