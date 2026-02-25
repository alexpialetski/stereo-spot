# Secrets Manager: Hugging Face token for SageMaker inference container.
# Create the secret here; set the token value manually (one-time) via AWS Console or CLI:
#   aws secretsmanager put-secret-value --secret-id <secret_id> --secret-string "<your_hf_token>"

resource "aws_secretsmanager_secret" "hf_token" {
  name        = "${local.name}/hf-token"
  description = "Hugging Face token for StereoCrafter model download in SageMaker container"
  tags        = { Name = "${local.name}/hf-token" }
}

# Optional: placeholder value so the secret exists before first put-secret-value.
# Remove this block and run put-secret-value after first apply with your real HF token.
resource "aws_secretsmanager_secret_version" "hf_token_placeholder" {
  secret_id = aws_secretsmanager_secret.hf_token.id
  secret_string = jsonencode({
    # Replace with your Hugging Face token (e.g. from https://huggingface.co/settings/tokens)
    # then run: aws secretsmanager put-secret-value --secret-id <id> --secret-string '{"token":"hf_xxx"}'
    token = "REPLACE_ME"
  })
}

# yt-dlp cookies for YouTube (Netscape format). Created by default; set value via root update-ytdlp-cookies target (see docs). Media-worker only uses it when enable_youtube_ingest is true.
resource "aws_secretsmanager_secret" "ytdlp_cookies" {
  name        = "${local.name}/ytdlp-cookies"
  description = "yt-dlp cookies file (Netscape format) for YouTube; used by media-worker ingest"
  tags        = { Name = "${local.name}/ytdlp-cookies" }
}

resource "aws_secretsmanager_secret_version" "ytdlp_cookies_placeholder" {
  secret_id     = aws_secretsmanager_secret.ytdlp_cookies.id
  secret_string = jsonencode({ cookies = "REPLACE_ME" })
}

# VAPID keypair for Web Push (web-ui). Generated in Terraform (tls_private_key + PEM-to-VAPID script) and stored in Secrets Manager.
resource "aws_secretsmanager_secret" "vapid" {
  name        = "${local.name}/vapid-web-push"
  description = "VAPID public/private keypair for Web Push notifications (web-ui)"
  tags        = { Name = "${local.name}/vapid-web-push" }
}

resource "tls_private_key" "vapid" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

data "external" "vapid_keys" {
  program = ["python3", "${path.module}/scripts/pem_to_vapid.py"]
  query = {
    private_key_pem = tls_private_key.vapid.private_key_pem
  }
}

resource "aws_secretsmanager_secret_version" "vapid" {
  secret_id = aws_secretsmanager_secret.vapid.id
  secret_string = jsonencode({
    vapid_public_key  = data.external.vapid_keys.result.vapid_public_key
    vapid_private_key = data.external.vapid_keys.result.vapid_private_key
  })
}
