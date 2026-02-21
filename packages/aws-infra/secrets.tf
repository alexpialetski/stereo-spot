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
