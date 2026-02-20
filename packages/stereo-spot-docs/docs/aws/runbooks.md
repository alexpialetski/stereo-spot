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

Default stereo-inference settings (in code) use **GPU encoding** (`--video-codec h264_nvenc`), **faster stereo method** (`--method row_flow_v3_sym`), **max 30 FPS** (`--max-fps 30`), and **batch size** from env `IW3_BATCH_SIZE` (default 8). Default instance type is **ml.g4dn.2xlarge** (Terraform variable `sagemaker_instance_type`).

If conversion is still too slow, check CloudWatch metrics for the endpoint (e.g. **SageMaker → Endpoints → stereo-spot-inference → Monitor**): **GPUUtilization**, **GPUMemoryUtilization**, **CPUUtilization**.

- **GPU util &lt; 80% and GPU memory &lt; 50%:** Consider a **larger instance** (e.g. `ml.g5.2xlarge`); set Terraform variable `sagemaker_instance_type` and run `terraform apply`, then update the endpoint to the new config.
- **GPU memory near 100%:** Set `IW3_LOW_VRAM=1` in the SageMaker model environment to reduce VRAM use (may be slightly slower). Or lower `IW3_BATCH_SIZE` (e.g. 4).
- **Want faster at cost of quality:** Set env such as `IW3_MAX_FPS` (e.g. 24) or a lower-quality preset in the SageMaker container. See [nunif/iw3](https://github.com/nagadomi/nunif) for available flags.
- **ETA in web UI:** Update `eta_seconds_per_mb_by_instance_type` in `variables.tf` for the instance type you use so the UI shows a realistic estimate.

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

Replace `<JOB_ID>` with the job UUID.
