# Terraform Module: aws-infra

This module provisions the **data plane** for stereo-spot: S3 buckets, SQS queues (with DLQs), DynamoDB tables, CloudWatch alarms, and **S3 event notifications** (S3 → SQS, no Lambda). It uses the AWS S3 backend from the `aws-infra-setup` project.

## Backend Configuration

This module uses the `backend.config` file from the `aws-infra-setup` project. Run `nx run aws-infra-setup:terraform-apply` first (if not already), then `nx run aws-infra:terraform-init` so the backend is configured.

## Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `region` | AWS region (override via `TF_VAR_region`, e.g. from `.env`) | `us-east-1` |
| `name_prefix` | Prefix for resource names | `stereo-spot` |
| `dlq_max_receive_count` | Max receive count before message goes to DLQ | `5` |

## Resources

### S3

- **Input bucket** (`stereo-spot-input-<account_id>`): User uploads to `input/{job_id}/source.mp4`; chunking-worker writes segments to `segments/{job_id}/...`. No lifecycle rule on this bucket.
- **Output bucket** (`stereo-spot-output-<account_id>`): Video-worker writes `jobs/{job_id}/segments/{segment_index}.mp4`; reassembly-worker writes `jobs/{job_id}/final.mp4`. **Lifecycle rule**: objects under prefix `jobs/` that are **tagged** with `stereo-spot-lifecycle = expire-segments` expire after **1 day**. The video-worker must tag segment outputs with this tag; `final.mp4` is not tagged and is retained.

### S3 event notifications (input bucket → SQS)

Two event flows are configured on the **input bucket** (S3 → SQS direct, no Lambda):

1. **Full-file upload → chunking queue**  
   Prefix `input/`, suffix `.mp4` → **chunking queue**. When the user uploads to `input/{job_id}/source.mp4`, S3 sends the event (bucket, key) to the chunking queue; the chunking-worker consumes it and runs ffmpeg chunking.

2. **Segment upload → video-worker queue**  
   Prefix `segments/`, suffix `.mp4` → **video-worker queue**. When the chunking-worker uploads segment files to `segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4`, S3 sends the event to the video-worker queue; the video-worker consumes it and runs inference.

Queue policies allow the input bucket to send messages to the chunking and video-worker queues. Workers already consume raw S3 events; no code changes required.

### SQS

- **Chunking queue** + **chunking DLQ** (redrive after `dlq_max_receive_count`).
- **Video-worker queue** + **video-worker DLQ**.
- **Reassembly queue** + **reassembly DLQ**.

Visibility timeouts: chunking 15 min, video-worker 20 min, reassembly 10 min.

### DynamoDB

- **Jobs**: PK `job_id` (String). GSI `status-completed_at`: PK `status`, SK `completed_at` (Number) for “list completed jobs” (query `status = 'completed'`, descending by `completed_at`, pagination via `ExclusiveStartKey`).
- **SegmentCompletions**: PK `job_id`, SK `segment_index`. Query by `job_id` returns segments in order for reassembly.
- **ReassemblyTriggered**: PK `job_id`. TTL enabled on attribute `ttl` (e.g. set to `triggered_at + 90 days` by Lambda/worker).

### CloudWatch

- **DLQ alarms**: One alarm per DLQ (`ApproximateNumberOfMessagesVisible > 0`, 1 evaluation period). Alarms are named so the queue is identifiable (chunking-dlq, video-worker-dlq, reassembly-dlq). When any message is in a DLQ, the alarm fires for failed-message visibility. Optional: add an SNS topic for notifications (follow-up).

## Access patterns

1. **List completed jobs**: Query Jobs GSI `status-completed_at` with `status = 'completed'`, `ScanIndexForward = false`, pagination via `Limit` and `ExclusiveStartKey`.
2. **Get/update job by job_id**: GetItem / UpdateItem on Jobs.
3. **Query SegmentCompletions by job_id**: Query with PK `job_id`, ordered by `segment_index`.
4. **Conditional write to ReassemblyTriggered by job_id**: PutItem with condition (e.g. item must not exist) for idempotency.

## Outputs

See `outputs.tf`. Outputs expose: `input_bucket_name`, `output_bucket_name`, `chunking_queue_url`, `video_worker_queue_url`, `reassembly_queue_url`, `jobs_table_name`, `segment_completions_table_name`, `reassembly_triggered_table_name`. Use `nx run aws-infra:terraform-output` to write them to `terraform-outputs.env` (or consume via Terraform output in CI).

## Running Terraform

Ensure AWS credentials and region are set (e.g. via `.env` and your environment or Nx). Then:

```bash
nx run aws-infra-setup:terraform-init   # if backend not yet created
nx run aws-infra:terraform-init
nx run aws-infra:terraform-plan
nx run aws-infra:terraform-apply        # after reviewing plan
```

After apply: `aws s3 ls`, `aws sqs list-queues`, `aws dynamodb list-tables` to verify.
