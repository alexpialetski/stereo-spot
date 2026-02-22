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
- **Visibility timeout:** In `packages/aws-infra/sqs.tf` (chunking 900s, video-worker 2400s, reassembly 600s). Increase and `terraform apply` if workers need more time.
- **Force one task (testing):** Load `packages/aws-infra/.env`, then:
  ```bash
  aws ecs update-service --cluster $ECS_CLUSTER_NAME --service media-worker --desired-count 1 --region us-east-1
  aws ecs update-service --cluster $ECS_CLUSTER_NAME --service video-worker --desired-count 1 --region us-east-1
  ```

---

## 3. Job stuck at chunking_complete

1. **Check queues** (load `.env`): `aws sqs get-queue-attributes --queue-url $VIDEO_WORKER_QUEUE_URL ...` and same for reassembly. Check ECS/CloudWatch logs for media-worker and video-worker.
2. **Check SegmentCompletions:** Query DynamoDB for the job_id; count should equal `Job.total_segments`. If so, video-worker should have sent to reassembly queue when the last completion was written.
3. **Check ReassemblyTriggered:** `aws dynamodb get-item --table-name $REASSEMBLY_TRIGGERED_TABLE_NAME --key '{"job_id":{"S":"<JOB_ID>"}}'`
4. **Manual reassembly trigger (one-off):**
   ```bash
   aws dynamodb put-item --table-name $REASSEMBLY_TRIGGERED_TABLE_NAME \
     --item '{"job_id":{"S":"<JOB_ID>"},"triggered_at":{"N":"'$(date +%s)'"},"ttl":{"N":"'$(($(date +%s) + 7776000))'"}}' \
     --condition-expression "attribute_not_exists(job_id)" --region us-east-1
   aws sqs send-message --queue-url $REASSEMBLY_QUEUE_URL --message-body '{"job_id":"<JOB_ID>"}' --region us-east-1
   ```
   Replace `<JOB_ID>`. Then refresh the job in the web UI.

---

## 4. SageMaker endpoint update

When `inference_backend=sagemaker`: build and push the image (`nx run stereo-inference:sagemaker-build`), then update the endpoint:

```bash
nx run stereo-inference:sagemaker-deploy
```

Or manually: create/update endpoint config with new image, then `aws sagemaker update-endpoint --endpoint-name <name> --endpoint-config-name <new_config_name>`.

**Optional iw3 tuning:** Set env in SageMaker model/endpoint (e.g. `IW3_LOW_VRAM=1`, or add `IW3_MAX_FPS`, `IW3_PRESET` in the container) for VRAM, fps, or file size. See [stereo-inference](/docs/packages/overview#stereo-inference) and this runbook for SageMaker env and update steps.

---

## 5. SageMaker performance tuning

Default stereo-inference settings use **software encoding** (`--video-codec libx264`) so the endpoint works on CPU or instances without NVENC. On **GPU instances** (e.g. **ml.g4dn.2xlarge**), set env **`IW3_VIDEO_CODEC=h264_nvenc`** in the SageMaker model for faster encoding. Other defaults: **stereo method** `row_flow_v3_sym`, **max 30 FPS**, **batch size** from `IW3_BATCH_SIZE` (default 8). Default instance type is **ml.g4dn.2xlarge** (Terraform variable `sagemaker_instance_type`).

If conversion is still too slow, check CloudWatch metrics for the endpoint (e.g. **SageMaker → Endpoints → stereo-spot-inference → Monitor**): **GPUUtilization**, **GPUMemoryUtilization**, **CPUUtilization**.

- **GPU util &lt; 80% and GPU memory &lt; 50%:** Consider a **larger instance** (e.g. `ml.g5.2xlarge`); set Terraform variable `sagemaker_instance_type` and run `terraform apply`, then update the endpoint to the new config.
- **GPU memory near 100%:** Set `IW3_LOW_VRAM=1` in the SageMaker model environment to reduce VRAM use (may be slightly slower). Or lower `IW3_BATCH_SIZE` (e.g. 4).
- **Want faster at cost of quality:** Set env such as `IW3_MAX_FPS` (e.g. 24) or a lower-quality preset in the SageMaker container. See [nunif/iw3](https://github.com/nagadomi/nunif) for available flags.
- **ETA in web UI:** ETA and the countdown are computed from recent completed jobs (lazy TTL cache). No Terraform or env configuration; once some jobs complete with `uploaded_at` and `source_file_size_bytes`, the UI shows estimates.

**iw3 fails with "Cannot load libnvidia-encode.so.1"** — Library not found. The image installs `libnvidia-encode-470` and sets `LD_LIBRARY_PATH`; if it still fails, use **`libx264`**.

**iw3 fails with "Driver does not support the required nvenc API version. Required: 13.0 Found: 11.1"** — The loaded libavcodec was built for NVENC 13.0 (e.g. from a PyAV **binary wheel** or an old image). The inference image is intended to build FFmpeg 5.1 from source with **nv-codec-headers n11.1.5.2** (API 11.1) and PyAV **from source** (`--no-binary av`) so **h264_nvenc** works on ml.g4dn (driver 470). Fix: **rebuild the image without cache** so the av layer is built from source against `/usr/local` FFmpeg, then **redeploy** the endpoint (e.g. `nx run stereo-inference:sagemaker-build` with cache disabled or clear CodeBuild cache, then `nx run stereo-inference:sagemaker-deploy`). If using CodeBuild, trigger a build with cache cleared so the `pip install --no-binary av` layer is not reused from a previous run that may have used a wheel.

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

The job detail page uses Server-Sent Events (SSE) to poll progress. If the UI stays at "Processing segments" after the job has completed:

1. **Consistent read:** The web-ui events endpoint uses **strongly consistent** reads for the job store so the completion status is seen as soon as the reassembly worker updates it. If you are on an older deploy, redeploy so the backend uses `consistent_read=True` for the progress stream.
2. **Load balancer idle timeout:** If the ALB (or proxy) idle timeout is shorter than the time to complete, the SSE connection may close before the final event. Increase the ALB idle timeout (e.g. 600s) so long-running conversions keep the stream open until completion.

---

## 8. Logs by job_id

CloudWatch Logs: log groups for web-ui, media-worker, video-worker (e.g. `/ecs/stereo-spot-web-ui`, etc.). In **Logs Insights**, select those groups and query:

```
fields @timestamp, @logStream, @message
| filter @message like /job_id=<JOB_ID>/
| sort @timestamp asc
```

Replace `<JOB_ID>` with the job UUID. When the web UI is configured with `NAME_PREFIX` (and region, e.g. via ECS), the job detail page shows an **Open logs** link that opens Logs Insights with these log groups and the above query pre-filled for that job.

**SSE progress stream (web-ui):** To see how each progress stream ended, filter for `events stream` in the web-ui log group. You should see one of: `events stream started`, then later `events stream ended (completed)`, `events stream ended (timeout)`, or `events stream ended (client disconnect)`. Use this to confirm whether the server saw the job as completed or the stream timed out / client disconnected.
