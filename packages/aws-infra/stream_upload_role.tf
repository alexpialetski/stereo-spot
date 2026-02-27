# IAM role for minting scoped S3 upload credentials (stream_input/{session_id}/*).
# Web-ui assumes this role and passes a session policy to restrict to one session.
# Use AssumeRole instead of GetFederationToken so it works with session credentials (SSO, assumed role).

data "aws_iam_policy_document" "stream_upload_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.web_ui_task.arn]
    }
  }
  # Allow any principal in this account (e.g. local dev with SSO/assumed role) to assume for testing
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }
  }
}

resource "aws_iam_role" "stream_upload" {
  name               = "${local.name}-stream-upload"
  assume_role_policy = data.aws_iam_policy_document.stream_upload_trust.json
  tags               = { Name = "${local.name}-stream-upload" }
}

resource "aws_iam_role_policy" "stream_upload" {
  name   = "stream-upload"
  role   = aws_iam_role.stream_upload.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:AbortMultipartUpload"]
        Resource = "${aws_s3_bucket.input.arn}/stream_input/*"
      }
    ]
  })
}

# Web-ui task can assume this role (in addition to GetFederationToken for long-term creds)
resource "aws_iam_role_policy" "web_ui_task_stream_upload_assume" {
  name   = "stream-upload-assume"
  role   = aws_iam_role.web_ui_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sts:AssumeRole"]
        Resource = [aws_iam_role.stream_upload.arn]
      }
    ]
  })
}
