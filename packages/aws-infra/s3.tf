# Input bucket: user uploads source to input/{job_id}/source.mp4; chunking-worker writes segments to segments/{job_id}/...
resource "aws_s3_bucket" "input" {
  bucket = "${local.name}-input-${local.account_id}"

  tags = merge(local.common_tags, {
    Name = "${local.name}-input"
  })
}

resource "aws_s3_bucket_versioning" "input" {
  bucket = aws_s3_bucket.input.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Output bucket: video-worker writes jobs/{job_id}/segments/{i}.mp4; reassembly-worker writes jobs/{job_id}/final.mp4
resource "aws_s3_bucket" "output" {
  bucket = "${local.name}-output-${local.account_id}"

  tags = merge(local.common_tags, {
    Name = "${local.name}-output"
  })
}

resource "aws_s3_bucket_versioning" "output" {
  bucket = aws_s3_bucket.output.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Lifecycle: expire segment objects under jobs/*/segments/ after 1 day.
# Objects must be tagged with stereo-spot-lifecycle = expire-segments (video-worker tags segment outputs).
# final.mp4 is not tagged, so it is retained.
resource "aws_s3_bucket_lifecycle_configuration" "output" {
  bucket = aws_s3_bucket.output.id

  rule {
    id     = "expire-segment-outputs"
    status = "Enabled"

    filter {
      and {
        prefix = "jobs/"
        tags = {
          "stereo-spot-lifecycle" = "expire-segments"
        }
      }
    }

    expiration {
      days = 1
    }
  }
}
