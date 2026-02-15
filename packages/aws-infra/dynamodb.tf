# Jobs table: PK job_id; GSI status-completed_at for list completed jobs
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

  global_secondary_index {
    name            = "status-completed_at"
    hash_key        = "status"
    range_key       = "completed_at"
    projection_type = "ALL"
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-jobs"
  })
}

# SegmentCompletions: PK job_id, SK segment_index; video-worker writes; reassembly Lambda/worker read
# Stream enabled for reassembly-trigger Lambda (invoked when new segment completion is written)
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

  tags = merge(local.common_tags, {
    Name = "${local.name}-segment-completions"
  })
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

  tags = merge(local.common_tags, {
    Name = "${local.name}-reassembly-triggered"
  })
}
