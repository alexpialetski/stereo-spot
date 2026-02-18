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

If a worker regularly needs more time than the visibility timeout, increase the value in `sqs.tf` and run `terraform apply`. Visibility timeout should be at least as long as the maximum time a single message might be processed (otherwise the message can become visible again and be processed twice). For **video-worker** with SageMaker, the end-to-end time is dominated by the endpoint; use at least 2–3× the expected segment processing time (e.g. 15–20 min for ~5 min segments).

### SQS long polling

Media-worker and video-worker receive messages using **SQS long polling** (configured in `packages/aws-adapters`). The receive call blocks for up to **20 seconds** (default) waiting for a message, so new messages are picked up quickly when a task is running. Optional env var **`SQS_LONG_POLL_WAIT_SECONDS`** (0–20) overrides the wait; set in the ECS task definition if you need to change it (e.g. 0 for short polling in tests).

### Why media-worker and video-worker show 0/0 tasks

Both workers are configured with **desired count 0** and scale **from zero** using Application Auto Scaling on SQS queue depth:

- **media-worker:** scales on `stereo-spot-chunking` queue (target 10 messages per task).
- **video-worker:** scales on `stereo-spot-video-worker` queue (target 10 messages per task).

So **0 running tasks is normal when the queues are empty or have few messages**. Target-tracking keeps “messages per task” near 10; if the queue has fewer than ~10 messages, desired count can stay 0 (e.g. 4 messages → 4/10 → 0 tasks). Scale-out typically happens when backlog approaches or exceeds the target (or after a short cooldown).

**To get tasks running:**

1. **Let scaling run:** Add more work (e.g. create a job and upload a video) so queue depth grows; scaling will add tasks (scale-out cooldown is 60 seconds).
2. **Temporarily force one task (e.g. for testing):**
   ```bash
   aws ecs update-service --cluster <ECS_CLUSTER_NAME> --service media-worker --desired-count 1 --region us-east-1
   aws ecs update-service --cluster <ECS_CLUSTER_NAME> --service video-worker --desired-count 1 --region us-east-1
   ```
   Auto Scaling may change desired count again when it evaluates the queues.
3. **Lower the scale-out threshold:** In `packages/aws-infra/ecs.tf`, reduce `target_value` in the `target_tracking_scaling_policy_configuration` (e.g. from 10.0 to 1.0) so that even 1–2 messages can trigger a task. Then run `terraform apply`.

### Job stuck at chunking_complete

When a job shows **status = chunking_complete** but never moves to **completed**, the pipeline after chunking is failing. Flow: segments → S3 events → video-worker queue → video-worker (writes SegmentCompletions) → **Lambda** (DynamoDB Stream on SegmentCompletions) → reassembly queue → media-worker (reassembly) → final.mp4 and Job completed.

**1. Check queues (load `packages/aws-infra/.env` first):**

```bash
# Message counts (visible + in-flight)
aws sqs get-queue-attributes --queue-url "$CHUNKING_QUEUE_URL" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --region us-east-1
aws sqs get-queue-attributes --queue-url "$VIDEO_WORKER_QUEUE_URL" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --region us-east-1
aws sqs get-queue-attributes --queue-url "$REASSEMBLY_QUEUE_URL" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --region us-east-1
```

- **Chunking:** Should be 0 after chunking; if messages are stuck, media-worker may be failing (check ECS/CloudWatch logs for media-worker).
- **Video-worker:** If messages are visible, video-worker may not be running or is failing (check ECS/CloudWatch logs for video-worker). If in-flight only, wait or check for timeouts.
- **Reassembly:** If 0 and job is still chunking_complete, the **reassembly-trigger Lambda** likely never sent a message (see step 2).

**2. Check SegmentCompletions and Lambda:**

- **DynamoDB:** Query `SegmentCompletions` for the job_id. Count should equal `Job.total_segments`. If count is correct, the Lambda should have run when the last completion was written.
- **Lambda logs:** In CloudWatch, open the log group for the reassembly-trigger Lambda (e.g. `/aws/lambda/stereo-spot-reassembly-trigger`). Look for invocations when the last segment completion was written. Logs now include `job_id`, `should trigger`, `created ReassemblyTriggered`, `sending to reassembly queue`, or reasons for skip (job not found, status not chunking_complete, count ≠ total_segments). If the Lambda was never invoked, check that the SegmentCompletions table has **DynamoDB Streams** enabled and the Lambda event source mapping is active.

**3. Check ReassemblyTriggered:**

```bash
aws dynamodb get-item --table-name "$REASSEMBLY_TRIGGERED_TABLE_NAME" --key '{"job_id":{"S":"<JOB_ID>"}}' --region us-east-1
```

If no item exists for the job and SegmentCompletions count equals total_segments, the Lambda either did not run or failed before the conditional put (check Lambda logs and errors).

**4. Manual reassembly trigger (one-off fix):**

If you’ve confirmed SegmentCompletions count is correct and the Lambda did not send to the reassembly queue, you can send the reassembly message manually and create the lock item so only one reassembly runs:

```bash
# Create ReassemblyTriggered (so media-worker doesn’t reject as duplicate)
aws dynamodb put_item --table-name "$REASSEMBLY_TRIGGERED_TABLE_NAME" \
  --item '{"job_id":{"S":"<JOB_ID>"},"triggered_at":{"N":"'$(date +%s)'"},"ttl":{"N":"'$(($(date +%s) + 7776000))'"}}' \
  --condition-expression "attribute_not_exists(job_id)" --region us-east-1

# Send to reassembly queue (JSON body with job_id)
aws sqs send-message --queue-url "$REASSEMBLY_QUEUE_URL" \
  --message-body '{"job_id":"<JOB_ID>"}' --region us-east-1
```

Replace `<JOB_ID>` with the stuck job’s ID. Then refresh the job in the web UI; media-worker should process the message and write final.mp4.

**5. Where to find logs:**

- **ECS tasks (media-worker, video-worker):** CloudWatch Logs, log groups `/ecs/stereo-spot-media-worker` and `/ecs/stereo-spot-video-worker` (or as set in Terraform). Stream prefix `ecs`. Workers now log job_id, segment_index, and key steps (chunking start/complete, reassembly received/completed, video-worker start/complete).
- **Reassembly-trigger Lambda:** CloudWatch Logs, log group `/aws/lambda/<reassembly-trigger-function-name>`.

---

## 4. Inference endpoint update and HF token rotation

Inference is **backend-switchable** (Terraform `inference_backend`: `sagemaker` or `http`). Use the matching deploy step after building the image.

### Updating the SageMaker inference image (when `inference_backend=sagemaker`)

The **stereocrafter-sagemaker** image (iw3/nunif: 2D→stereo SBS/anaglyph) is built and pushed by **AWS CodeBuild**. Run `nx run stereocrafter-sagemaker:sagemaker-build` (after committing and pushing your changes); it triggers CodeBuild to clone the repo, build the image, and push to ECR. Then run `nx run stereocrafter-sagemaker:sagemaker-deploy` to update the SageMaker endpoint to use the new image.

After the image is in ECR (or if you build and push locally):

1. **Create a new endpoint configuration** (or update in Terraform with the same image tag) so SageMaker uses the new image. If you use Terraform with `ecs_image_tag` (e.g. `latest`), re-pushing the same tag and running **update-endpoint** is enough.
2. **Update the endpoint** to use the new configuration:
   ```bash
   aws sagemaker update-endpoint --endpoint-name <SAGEMAKER_ENDPOINT_NAME> --endpoint-config-name <new_config_name>
   ```
   Or with Terraform: change the endpoint config (e.g. new image tag), apply, then update the endpoint in the console or via CLI to point to the new config.

The endpoint will roll to the new config; in-flight invocations may complete on the old instance.

### Optional iw3 tuning (SageMaker inference container)

The inference container uses [iw3](https://github.com/nagadomi/nunif) (nunif). Useful options you can expose later via env or request body:

| Goal | iw3 option | Notes |
|------|------------|--------|
| **Reduce VRAM** (smaller GPUs, e.g. g5.xlarge) | `IW3_LOW_VRAM=1` | Already supported: set this env in the SageMaker model/endpoint config to pass `--low-vram` to iw3. |
| **Preserve 60fps** | `--max-fps 128` | By default iw3 limits to 30fps; add this to allow 60fps (longer processing). |
| **Smaller output file** | `--preset medium`, `--video-codec libx265` | Reduces bitrate / file size at some encode cost. |
| **Older GPUs** (pre–GeForce 20) | `--disable-amp` | Disables FP16 if you see slowdowns or errors. |

To add these, extend `serve.py` to read env vars (e.g. `IW3_MAX_FPS`, `IW3_PRESET`) and append the corresponding flags to the iw3 CLI invocation.

### Rotating the Hugging Face token (optional)

The **current** iw3 inference image bakes pre-trained models into the image and **does not use** a Hugging Face token at startup. If you later add a container that downloads gated models from Hugging Face at startup, the HF token can be stored in **Secrets Manager** (secret ARN in env `HF_TOKEN_ARN`). To rotate that token:

1. **Put a new secret value:**
   ```bash
   aws secretsmanager put-secret-value --secret-id <hf_token_secret_arn> --secret-string '{"token":"hf_NEW_TOKEN"}'
   ```
2. **Redeploy the SageMaker endpoint** so new instances pull the updated secret: run `nx run stereocrafter-sagemaker:sagemaker-deploy` (creates new model/endpoint config and updates the endpoint). Existing instances keep the old value until replaced.

---

## 5. Querying logs by job_id (correlation)

All services log **job_id** (and where relevant **segment_index**) so you can trace one job across the pipeline in CloudWatch Logs. **Error and exception logs** also include `job_id` (or `job_id=?` when the message body cannot be parsed, e.g. invalid JSON), so failed steps are searchable by job.

**Log groups (typical names):**

- Web UI: `/ecs/stereo-spot-web-ui` (or as in your ECS task definition)
- Media-worker: `/ecs/stereo-spot-media-worker`
- Video-worker: `/ecs/stereo-spot-video-worker`
- Reassembly-trigger Lambda: `/aws/lambda/<reassembly-trigger-function-name>`
- SageMaker endpoint: `/aws/sagemaker/Endpoints/<endpoint-name>` (when `inference_backend=sagemaker` and endpoint logging is enabled)

**CloudWatch Logs Insights – one job across all services:**

1. In the AWS console, open **CloudWatch → Logs → Logs Insights**.
2. Select the log groups above (or the ones you use).
3. Run a query (replace `<JOB_ID>` with the job UUID, e.g. `4badaf04-9b49-443e-84fd-26f4b9bef85d`):

```
fields @timestamp, @logStream, @message
| filter @message like /job_id=<JOB_ID>/
| sort @timestamp asc
```

4. Optional: narrow to one service by selecting only that log group, or add `| filter @logStream like /media-worker/` (etc.) to the query.

All pipeline steps for that job (web create/detail/play, chunking, video-worker, Lambda trigger, reassembly, SageMaker invocations) will appear in time order when they include `job_id=<JOB_ID>` in the message.
