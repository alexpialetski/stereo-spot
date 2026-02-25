---
sidebar_position: 4
---

# AWS runbooks

AWS-specific procedures. For generic concepts see [Runbooks (generic)](/docs/runbooks).

## 1. DLQ handling

**Inspect:** Get DLQ URL (Terraform output or console), then:
```bash
aws sqs receive-message --queue-url <DLQ_URL> --max-number-of-messages 10 --visibility-timeout 0
```

**Replay:** Send body to main queue, then delete from DLQ:
```bash
aws sqs send-message --queue-url <MAIN_QUEUE_URL> --message-body "<body>"
aws sqs delete-message --queue-url <DLQ_URL> --receipt-handle <receipt_handle>
```

**Discard:** `aws sqs purge-queue --queue-url <DLQ_URL>` (use with care).

**Chunking DLQ with job completed:** If a job finished successfully but `stereo-spot-chunking-dlq` has 1 message, it is often a **duplicate S3 event**. S3 can send more than one notification for the same object; one message is processed and deleted, the other may be retried (e.g. "job not found" due to timing, or a transient exception) until `maxReceiveCount` (default 5), then moved to the DLQ. To confirm, receive the message and check the body: same `input/<job_id>/source.mp4` as the completed job. You can safely **discard** that DLQ message (delete it or purge after inspection). No code change is required for correctness; optionally you can add idempotency (e.g. S3 event sequencer) to avoid duplicate processing.

---

## 2. ECS scaling and visibility timeout

- **Max capacity:** In Terraform (`ecs.tf`): e.g. `aws_appautoscaling_target.media_worker.max_capacity`, or variable `ecs_video_worker_max_capacity` for video-worker.
- **Visibility timeout:** In `packages/aws-infra/sqs.tf` (chunking 900s, video-worker 2400s, reassembly 3600s). Reassembly is 1 h so download + concat + upload of large segments can finish; increase and `terraform apply` if needed.
- **Force one task (testing):** Load `packages/aws-infra/.env`, then:
  ```bash
  aws ecs update-service --cluster $ECS_CLUSTER_NAME --service media-worker --desired-count 1 --region us-east-1
  aws ecs update-service --cluster $ECS_CLUSTER_NAME --service video-worker --desired-count 1 --region us-east-1
  ```

---

## 3. Job stuck at chunking_complete

1. **Check queues** (load `.env`): `aws sqs get-queue-attributes --queue-url $VIDEO_WORKER_QUEUE_URL ...` and same for reassembly. Check ECS/CloudWatch logs for media-worker and video-worker.
2. **Check SegmentCompletions:** Query DynamoDB for the job_id; count should equal `Job.total_segments`. If so, video-worker should have sent to reassembly queue when the last completion was written.
3. **Check ReassemblyTriggered:** `aws dynamodb get-item --table-name $REASSEMBLY_TRIGGERED_TABLE_NAME --key '{"job_id":{"S":"<JOB_ID>"}}'` If the item has `reassembly_started_at` but the job never completed, a worker likely hit **reassembly queue visibility timeout** (message became visible again, another worker acked it without doing work). Fix: set reassembly queue `VisibilityTimeout` to 3600 (e.g. `aws sqs set-queue-attributes --queue-url $REASSEMBLY_QUEUE_URL --attributes VisibilityTimeout=3600`), delete the ReassemblyTriggered item, put a fresh item (same as below), then send the message again.
4. **Manual reassembly trigger (one-off):**
   ```bash
   aws dynamodb put-item --table-name $REASSEMBLY_TRIGGERED_TABLE_NAME \
     --item '{"job_id":{"S":"<JOB_ID>"},"triggered_at":{"N":"'$(date +%s)'"},"ttl":{"N":"'$(($(date +%s) + 7776000))'"}}' \
     --condition-expression "attribute_not_exists(job_id)" --region us-east-1
   aws sqs send-message --queue-url $REASSEMBLY_QUEUE_URL --message-body '{"job_id":"<JOB_ID>"}' --region us-east-1
   ```
   Replace `<JOB_ID>`. Then refresh the job in the web UI.

**Only one SegmentCompletion despite all segments succeeding (video-worker):** If SageMaker logs show all segments "invocations complete" but only one `output-events: ... SageMaker success -> ...` appears (e.g. only segment 2), the success S3 events for the other segments either never reached the output-events queue or were processed after the **invocation store TTL** (2 h). When the store record is missing, the worker logs "no invocation record for ... (idempotent delete)" and does not write a SegmentCompletion. Fix: add the missing SegmentCompletions manually and trigger reassembly (see step 4 above). To reduce recurrence for long-running inference, increase inference invocations TTL (e.g. in `stereo_spot_aws_adapters.dynamodb_stores`: `INFERENCE_INVOCATIONS_TTL_SECONDS`) and redeploy the video-worker.

**"no invocation record for failure" (video-worker):** These WARNINGs refer to **sagemaker-async-failures/** objects. The invocation store is keyed by the **success** response URI (`sagemaker-async-responses/...`), so failure events never find a record. The worker releases the inference semaphore when it sees a failure with no record (to avoid leaking slots). If a job has one segment never scheduled (e.g. segment 2 of 3; video-worker queue has 1 message), the running task may be stuck holding all semaphore slots—**restart the video-worker service** so the pending message is picked up by a fresh task.

**What’s inside sagemaker-async-failures/*.out:** Download one (e.g. `aws s3 cp s3://$OUTPUT_BUCKET_NAME/sagemaker-async-failures/<id>-error.out -`). The body is usually **"Timed out uploading object (bucket: ..., key: sagemaker-async-responses/...)"**. That means the async invocation (container run + uploading the result to S3) exceeded **InvocationTimeoutSeconds**. So no success object is written—only the failure—and the video-worker never gets a success event (so no SegmentCompletion and, before the semaphore fix, the slot stayed held). **Fix:** Increase the timeout so long segments succeed. Set **SAGEMAKER_INVOKE_TIMEOUT_SECONDS=3600** (1 hour, max allowed) in the video-worker ECS task environment (Terraform or console). Default in code is 1200 (20 min); if a segment takes longer (e.g. 27 min), the invocation times out and you get these failures. After increasing the timeout and redeploying the video-worker, new invocations will use the higher limit.

**Reassembly logged "concat 3 segments" but no "completed":** Check S3 for `jobs/<job_id>/final.mp4`. **If it exists**, the video-worker should set the job to completed when it sees the S3 event; if the job is still chunking_complete (e.g. event was missed), update the job manually: `aws dynamodb update-item --table-name $JOBS_TABLE_NAME --key '{"job_id":{"S":"<JOB_ID>"}}' --update-expression "SET #st = :st, #ca = :ca" --expression-attribute-names '{"#st":"status","#ca":"completed_at"}' --expression-attribute-values '{":st":{"S":"completed"},":ca":{"N":"'$(date +%s)'"}}' --region us-east-1`. **If final.mp4 is missing** (e.g. media-worker OOM during concat/upload), the ReassemblyTriggered item has `reassembly_started_at` set so new messages get "lock not acquired". Reset and re-trigger reassembly:

   ```bash
   # 1. Delete the lock so a worker can run reassembly again
   aws dynamodb delete-item --table-name $REASSEMBLY_TRIGGERED_TABLE_NAME \
     --key '{"job_id":{"S":"<JOB_ID>"}}' --region us-east-1
   # 2. Put a fresh lock item (no reassembly_started_at) and send message
   aws dynamodb put-item --table-name $REASSEMBLY_TRIGGERED_TABLE_NAME \
     --item '{"job_id":{"S":"<JOB_ID>"},"triggered_at":{"N":"'$(date +%s)'"},"ttl":{"N":"'$(($(date +%s) + 7776000))'"}}' \
     --condition-expression "attribute_not_exists(job_id)" --region us-east-1
   aws sqs send-message --queue-url $REASSEMBLY_QUEUE_URL --message-body '{"job_id":"<JOB_ID>"}' --region us-east-1
   ```
   Replace `<JOB_ID>`. To reduce OOM risk, increase the media-worker ECS task memory (e.g. in Terraform `ecs.tf`: `media_worker` task definition `memory`) and redeploy.

---

## 4. SageMaker endpoint update

When `inference_backend=sagemaker`: build and push the image (`nx run stereo-inference:inference-build`), then update the endpoint:

```bash
nx run stereo-inference:inference-redeploy
```

Or manually: create/update endpoint config with new image, then `aws sagemaker update-endpoint --endpoint-name <name> --endpoint-config-name <new_config_name>`.

**Optional iw3 tuning:** Set env in SageMaker model/endpoint (e.g. `IW3_LOW_VRAM=1`, or add `IW3_MAX_FPS`, `IW3_PRESET` in the container) for VRAM, fps, or file size. See [stereo-inference](/docs/packages/overview#stereo-inference) and this runbook for SageMaker env and update steps.

---

## 5. SageMaker performance tuning

Default stereo-inference settings use **software encoding** (`--video-codec libx264`) so the endpoint works on CPU or instances without NVENC. On **GPU instances** (e.g. **ml.g4dn.xlarge**), set env **`IW3_VIDEO_CODEC=h264_nvenc`** in the SageMaker model for faster encoding. Other defaults: **stereo method** `row_flow_v3_sym`, **max 30 FPS**, **batch size** from `IW3_BATCH_SIZE` (default 8). Default instance type is **ml.g4dn.xlarge** (Terraform variable `sagemaker_instance_type`).

If conversion is still too slow, check CloudWatch metrics for the endpoint (e.g. **SageMaker → Endpoints → stereo-spot-inference → Monitor**): **GPUUtilization**, **GPUMemoryUtilization**, **CPUUtilization**.

- **GPU util &lt; 80% and GPU memory &lt; 50%:** Consider a **larger instance** (e.g. `ml.g5.2xlarge`); set Terraform variable `sagemaker_instance_type` and run `terraform apply`, then update the endpoint to the new config.
- **GPU memory near 100%:** Set `IW3_LOW_VRAM=1` in the SageMaker model environment to reduce VRAM use (may be slightly slower). Or lower `IW3_BATCH_SIZE` (e.g. 4).
- **Want faster at cost of quality:** Set env such as `IW3_MAX_FPS` (e.g. 24) or a lower-quality preset in the SageMaker container. See [nunif/iw3](https://github.com/nagadomi/nunif) for available flags.
- **ETA in web UI:** ETA and the countdown are computed from recent completed jobs (lazy TTL cache). No Terraform or env configuration; once some jobs complete with `uploaded_at` and `source_file_size_bytes`, the UI shows estimates.

**iw3 fails with "Cannot load libnvidia-encode.so.1"** — Library not found. The image installs `libnvidia-encode-470` and sets `LD_LIBRARY_PATH`; if it still fails, use **`libx264`**.

**iw3 fails with "Driver does not support the required nvenc API version. Required: 13.0 Found: 11.1"** — The loaded libavcodec was built for NVENC 13.0 (e.g. from a PyAV **binary wheel** or an old image). The inference image is intended to build FFmpeg 5.1 from source with **nv-codec-headers n11.1.5.2** (API 11.1) and PyAV **from source** (`--no-binary av`) so **h264_nvenc** works on ml.g4dn (driver 470). Fix: **rebuild the image without cache** so the av layer is built from source against `/usr/local` FFmpeg, then **redeploy** the endpoint (e.g. `nx run stereo-inference:inference-build --configuration=no-cache`, then `nx run stereo-inference:inference-redeploy`). If using CodeBuild, trigger a build with cache cleared so the `pip install --no-binary av` layer is not reused from a previous run that may have used a wheel.

---

## 6. SageMaker: "Failed to download object" (invocation request)

When the SageMaker endpoint logs **"Failed to download object (bucket: …, key: sagemaker-invocation-requests/…)"**, the inference container cannot read the request JSON that the video-worker uploads before calling `InvokeEndpointAsync`.

**Causes:**

1. **Request file not in S3** — Video-worker uploads to `s3://<OUTPUT_BUCKET>/sagemaker-invocation-requests/<job_id>/<segment_index>.json`. If the object is missing:
   - Check **video-worker** CloudWatch logs for the same `job_id`: you should see `"uploaded invocation request to s3://..."` (INFO). If that line is missing, the worker may have failed before the upload or the message never reached the worker.
   - Ensure the **video-worker** ECS task role has `s3:PutObject` on the output bucket (Terraform: `ecs.tf` video-worker task role).
   - Verify the object exists (after a repro):
     ```bash
     aws s3 ls s3://$OUTPUT_BUCKET_NAME/sagemaker-invocation-requests/<JOB_ID>/ --region us-east-1
     ```

2. **SageMaker endpoint role cannot read** — The endpoint execution role (Terraform: `sagemaker.tf` `aws_iam_role.sagemaker_endpoint`) must have `s3:GetObject` on the output bucket. Policy already allows `${aws_s3_bucket.output.arn}/*`; if you changed the bucket or policy, re-apply.

**Quick retry:** Restart the video-worker (force new deployment), then re-send the segment message to the video-worker queue so the worker uploads the request again and invokes the endpoint. See [Job stuck at chunking_complete](#3-job-stuck-at-chunking_complete) for queue URLs and optional manual reassembly.

---

## 7. Progress / SSE not updating to completed

The job detail page uses Server-Sent Events (SSE) for progress. When **JOB_EVENTS_QUEUE_URL** is set (e.g. ECS), the flow is event-driven: initial state from the store, then updates from the **job-events** queue (fed by EventBridge Pipes from DynamoDB streams). If the UI stays at "Processing segments" after the job has completed:

1. **EventBridge Pipes:** Confirm both Pipes exist and are **RUNNING** (jobs stream and segment_completions stream to job-events queue). In the AWS console, open EventBridge → Pipes and check the two job-events pipes.
2. **Job-events queue:** Confirm the web-ui task has **JOB_EVENTS_QUEUE_URL**, **JOBS_TABLE_STREAM_ARN**, and **SEGMENT_COMPLETIONS_TABLE_STREAM_ARN** and can receive from the queue (IAM: `sqs:ReceiveMessage`, `sqs:DeleteMessage`). If messages pile up, the consumer may be failing; check web-ui logs for "job-events receive failed" or "job-events message handling failed".
3. **Consistent read:** The initial state and consumer progress logic use strongly consistent reads where needed.
4. **Load balancer idle timeout:** If the ALB idle timeout is shorter than the time to complete, the SSE connection may close. Increase it (e.g. 600s) so long-running conversions keep the stream open.

**Job-events DLQ:** If the web-ui consumer fails repeatedly to process messages, they go to **stereo-spot-job-events-dlq**. Inspect with `aws sqs receive-message --queue-url <DLQ_URL>` (use the DLQ URL from Terraform output). A CloudWatch alarm fires when the job-events DLQ has messages.

---

## 8. Job-events Pipes and Web Push

- **EventBridge Pipes:** Two Pipes (Terraform: `pipes_job_events.tf`) feed the job-events SQS queue from the jobs and segment_completions DynamoDB streams. No Lambda; the web-ui consumer normalizes stream records and computes progress in-process, then pushes to SSE and Web Push.
- **Web-ui env (for job-events):** **JOB_EVENTS_QUEUE_URL**, **JOBS_TABLE_STREAM_ARN**, **SEGMENT_COMPLETIONS_TABLE_STREAM_ARN** (and **JOBS_TABLE_NAME**, **SEGMENT_COMPLETIONS_TABLE_NAME**, **AWS_REGION** for stores). Set by Terraform for the web-ui ECS task.
- **Web Push (optional):** Desktop notifications when jobs complete or fail require a secure context (HTTPS or localhost). The web UI serves the VAPID public key at **GET /api/vapid-public-key** only when the request is over HTTPS (direct or `X-Forwarded-Proto: https`); over HTTP it returns an empty key, so the notification prompt is not shown. Terraform creates a Secrets Manager secret for the VAPID keypair (`secrets.tf`: `vapid-web-push`) and populates it at apply time; the web-ui ECS task receives **VAPID_SECRET_ARN** and loads **VAPID_PUBLIC_KEY** and **VAPID_PRIVATE_KEY** at startup. Push subscriptions are stored in the **push_subscriptions** DynamoDB table. To enable Web Push in production, enable ALB HTTPS (place **alb-certificate.pem** and **alb-private-key.pem** at the project root, then apply) and use **WEB_UI_URL** (HTTPS when certs are present). For local dev, set **VAPID_PUBLIC_KEY** and **VAPID_PRIVATE_KEY** in env.

---

## 9. Logs by job_id

CloudWatch Logs: log groups for web-ui, media-worker, video-worker (e.g. `/ecs/stereo-spot-web-ui`, etc.). In **Logs Insights**, select those groups and query:

```
fields @timestamp, @logStream, @message
| filter @message like /job_id=<JOB_ID>/
| sort @timestamp asc
```

Replace `<JOB_ID>` with the job UUID. When the web UI is configured with `NAME_PREFIX` (and region, e.g. via ECS), the job detail page shows an **Open logs** link that opens Logs Insights with these log groups and the above query pre-filled for that job.

**SSE progress stream (web-ui):** Filter for `events stream` in the web-ui log group. You should see `events stream started`, then (when event-driven) updates from the job-events consumer, or (when polling) keepalives until `events stream ended (completed)`, `events stream ended (timeout)`, or `events stream ended (client disconnect)`.
