# Operational Runbooks

Procedures for common operations: chunking failure recovery, DLQ handling, and scaling.

---

## 1. Chunking failure recovery

**When to use:** The media-worker uploaded segment files to S3 (prefix `segments/{job_id}/`) but crashed or was killed before updating the Job in DynamoDB (e.g. before setting `total_segments` and `status=chunking_complete`). The job stays in `created` or `chunking_in_progress`, so the video-worker and reassembly pipeline never see it as ready.

**Goal:** Set the Job’s `total_segments` and `status=chunking_complete` in DynamoDB so that when the video-worker finishes all segments, the reassembly trigger Lambda can run.

### Option A: Recovery script (recommended)

A script in the repo lists S3 segments for the job, derives `total_segments` using the segment key parser from shared-types, and performs a single DynamoDB UpdateItem.

**Prerequisites:**

- From repo root: `pip install -e packages/shared-types`
- AWS credentials (env or profile) with access to the input bucket and Jobs table
- `INPUT_BUCKET_NAME` and `JOBS_TABLE_NAME` in the environment, or load `packages/aws-infra/.env` (e.g. from `nx run aws-infra:terraform-output`)

**Run:**

```bash
# Load Terraform outputs (if not already in env)
. packages/aws-infra/.env   # or export INPUT_BUCKET_NAME=... JOBS_TABLE_NAME=...

# With confirmation prompt
python scripts/chunking_recovery.py <job_id>

# Skip confirmation (e.g. in automation)
python scripts/chunking_recovery.py <job_id> --yes
```

The script lists objects under `s3://<input_bucket>/segments/<job_id>/`, parses each key with the shared-types segment key format (`segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4`), and updates the Job with `total_segments` and `status=chunking_complete`. It refuses to overwrite if the job is already `chunking_complete` or `completed`.

### Option B: Manual procedure (no script)

If you cannot run the script, use the same logic manually.

1. **List segment keys** in the input bucket under prefix `segments/{job_id}/`:
   ```bash
   aws s3api list-objects-v2 --bucket <INPUT_BUCKET_NAME> --prefix "segments/<job_id>/" --query 'Contents[].Key' --output text
   ```

2. **Derive total_segments** from the key format. Each key looks like:
   `segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4`
   - You can take `total_segments` from any one key (the middle number in the filename, e.g. `00042` in `00000_00042_anaglyph.mp4` means 42 segments).
   - Or use: `total_segments = max(segment_index over all keys) + 1` (segment_index is zero-based).

3. **Update the Job** in DynamoDB (only if the job is not already `chunking_complete` or `completed`):
   ```bash
   aws dynamodb update-item \
     --table-name <JOBS_TABLE_NAME> \
     --key '{"job_id": {"S": "<job_id>"}}' \
     --update-expression "SET #st = :st, total_segments = :ts" \
     --expression-attribute-names '{"#st": "status"}' \
     --expression-attribute-values '{":st": {"S": "chunking_complete"}, ":ts": {"N": "<total_segments>"}}'
   ```

Replace `<job_id>`, `<INPUT_BUCKET_NAME>`, `<JOBS_TABLE_NAME>`, and `<total_segments>` with the actual values.

---

## 2. DLQ handling

Each main queue (chunking, video-worker, reassembly) has a **dead-letter queue (DLQ)**. After `maxReceiveCount` failed receives, messages are moved to the DLQ. CloudWatch alarms fire when any message is in a DLQ (see `packages/aws-infra`).

### Inspect messages in a DLQ

List queues and receive messages:

```bash
# Get DLQ URL (from Terraform output or AWS console)
aws sqs get-queue-url --queue-name <name>-chunking-dlq   # or -video-worker-dlq, -reassembly-dlq

# Receive (without deleting) to inspect
aws sqs receive-message --queue-url <DLQ_URL> --max-number-of-messages 10 --visibility-timeout 0
```

Use the message body and attributes to decide whether to replay or discard.

### Replay (send back to main queue)

1. Get the **main queue URL** for that workload (chunking, video-worker, or reassembly).
2. For each message you want to retry: send the same body to the main queue, then delete the message from the DLQ:
   ```bash
   aws sqs send-message --queue-url <MAIN_QUEUE_URL> --message-body "<body>"
   aws sqs delete-message --queue-url <DLQ_URL> --receipt-handle <receipt_handle>
   ```
3. Fix the underlying cause (e.g. bug, bad input, or transient failure) before replaying, or messages may return to the DLQ again.

### Discard messages

If messages are known to be bad or no longer needed:

```bash
aws sqs purge-queue --queue-url <DLQ_URL>
```

This deletes all messages in the DLQ. Use only when you are sure you do not need to replay.

---

## 3. Adjusting ECS service max capacity and SQS visibility timeout

### ECS service max capacity

- **Media-worker:** Max capacity is fixed in Terraform (e.g. 10). To change it, edit `packages/aws-infra/ecs.tf` (`aws_appautoscaling_target.media_worker.max_capacity`) and run `terraform apply`.
- **Video-worker:** Max capacity is controlled by the variable `ecs_video_worker_max_capacity` (default 8). Set it in Terraform (e.g. `terraform.tfvars`) or pass `-var="ecs_video_worker_max_capacity=4"` and apply.

To change desired count temporarily without Terraform:

```bash
aws ecs update-service --cluster <ECS_CLUSTER_NAME> --service media-worker --desired-count 2
```

Temporary changes can be overwritten by Application Auto Scaling when it adjusts desired count based on queue depth.

### SQS visibility timeout

Visibility timeout is set per queue in Terraform (`packages/aws-infra/sqs.tf`):

- **Chunking:** 900 seconds (15 min) — chunking can take a while for large files.
- **Video-worker:** 1800 seconds (30 min) — GPU segment processing.
- **Reassembly:** 600 seconds (10 min).

If a worker regularly needs more time than the visibility timeout, increase the value in `sqs.tf` and run `terraform apply`. Visibility timeout should be at least as long as the maximum time a single message might be processed (otherwise the message can become visible again and be processed twice).
