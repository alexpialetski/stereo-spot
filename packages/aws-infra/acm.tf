# ALB HTTPS and YouTube ingest are driven by Terraform variables (see variables.tf).
# Certificates are imported via root script (update-alb-certificates); no cert content in state.
locals {
  enable_alb_https      = trimspace(var.load_balancer_certificate_id) != ""
  enable_youtube_ingest = var.enable_youtube_ingest
  alb_url               = local.enable_alb_https ? "https://${aws_lb.web_ui.dns_name}" : "http://${aws_lb.web_ui.dns_name}"
}
