locals {
  bucket_name = "terraform-state-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.region}"
}
