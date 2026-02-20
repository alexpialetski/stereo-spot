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
- **Visibility timeout:** In `packages/aws-infra/sqs.tf` (chunking 900s, video-worker 1800s, reassembly 600s). Increase and `terraform apply` if workers need more time.
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

## 5. Logs by job_id

CloudWatch Logs: log groups for web-ui, media-worker, video-worker (e.g. `/ecs/stereo-spot-web-ui`, etc.). In **Logs Insights**, select those groups and query:

```
fields @timestamp, @logStream, @message
| filter @message like /job_id=<JOB_ID>/
| sort @timestamp asc
```

Replace `<JOB_ID>` with the job UUID.
