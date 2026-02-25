# ALB HTTPS: when mkcert cert files exist at project root, enable HTTPS and HTTP→HTTPS redirect.
# YouTube ingest: when ytdlp_cookies.txt exists at project root, create ingest queue and cookies secret.
locals {
  alb_cert_body          = try(file("${path.module}/../../alb-certificate.pem"), "")
  alb_key_body           = try(file("${path.module}/../../alb-private-key.pem"), "")
  enable_alb_https       = trimspace(local.alb_cert_body) != "" && trimspace(local.alb_key_body) != ""
  alb_url                = local.enable_alb_https ? "https://${aws_lb.web_ui.dns_name}" : "http://${aws_lb.web_ui.dns_name}"
  enable_youtube_ingest  = fileexists("${path.module}/../../ytdlp_cookies.txt")
}

# Certificate from project root (alb-certificate.pem, alb-private-key.pem); see packages/aws-infra/README.md.
resource "aws_acm_certificate" "web_ui_alb" {
  count = local.enable_alb_https ? 1 : 0

  private_key      = local.alb_key_body
  certificate_body = local.alb_cert_body

  lifecycle {
    create_before_destroy = true
  }
}
