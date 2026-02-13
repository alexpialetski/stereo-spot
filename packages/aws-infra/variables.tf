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
