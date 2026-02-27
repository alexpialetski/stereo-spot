# Jobs table: PK job_id; GSI status-completed_at for completed; GSI status-created_at for in-progress
# Stream enabled for EventBridge Pipes (jobs stream -> job-events queue)
resource "aws_dynamodb_table" "jobs" {
  name         = "${local.name}-jobs"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "completed_at"
    type = "N"
  }

  attribute {
    name = "created_at"
    type = "N"
  }

  global_secondary_index {
    name            = "status-completed_at"
    hash_key        = "status"
    range_key       = "completed_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "status-created_at"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = { Name = "${local.name}-jobs" }
}

# SegmentCompletions: PK job_id, SK segment_index; video-worker writes and triggers reassembly (trigger-on-write); media-worker reads for concat
resource "aws_dynamodb_table" "segment_completions" {
  name         = "${local.name}-segment-completions"
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "job_id"
  range_key = "segment_index"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "segment_index"
    type = "N"
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = { Name = "${local.name}-segment-completions" }
}

# ReassemblyTriggered: PK job_id; TTL on ttl attribute; idempotency and media-worker lock
resource "aws_dynamodb_table" "reassembly_triggered" {
  name         = "${local.name}-reassembly-triggered"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { Name = "${local.name}-reassembly-triggered" }
}

# InferenceInvocations: PK output_location (S3 URI); correlates SageMaker async result to job/segment for output-events consumer
resource "aws_dynamodb_table" "inference_invocations" {
  name         = "${local.name}-inference-invocations"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "output_location"

  attribute {
    name = "output_location"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { Name = "${local.name}-inference-invocations" }
}

# StreamSessions: PK session_id; optional TTL for automatic expiry
resource "aws_dynamodb_table" "stream_sessions" {
  name         = "${local.name}-stream-sessions"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { Name = "${local.name}-stream-sessions" }
}

# Push subscriptions: Web Push subscription payloads for job-events notifications (web-ui stores, reads for sending)
resource "aws_dynamodb_table" "push_subscriptions" {
  name         = "${local.name}-push-subscriptions"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "endpoint"

  attribute {
    name = "endpoint"
    type = "S"
  }

  tags = { Name = "${local.name}-push-subscriptions" }
}
