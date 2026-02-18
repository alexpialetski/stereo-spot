# Terraform Module: aws-infra

This module provisions the **data plane** and **compute plane** for stereo-spot: S3 buckets, SQS queues (with DLQs), DynamoDB tables, CloudWatch alarms, **S3 event notifications** (S3 → SQS), **ECS cluster**, **ECR** repositories, **task definitions** and **ECS services** (Fargate for web-ui, media-worker, and video-worker), **CodeBuild** (stereocrafter-sagemaker image build), **SageMaker** (model, endpoint config, endpoint for StereoCrafter), **Secrets Manager** (Hugging Face token for SageMaker), **ALB** for web-ui, and **IAM task roles**. It uses the AWS S3 backend from the `aws-infra-setup` project.

## Backend Configuration

This module uses the `backend.config` file from the `aws-infra-setup` project. Run `nx run aws-infra-setup:terraform-apply` first (if not already), then `nx run aws-infra:terraform-init` so the backend is configured.

## Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `region` | AWS region (override via `TF_VAR_region`, e.g. from `.env`) | `us-east-1` |
| `name_prefix` | Prefix for resource names | `stereo-spot` |
| `dlq_max_receive_count` | Max receive count before message goes to DLQ | `5` |
| `ecs_image_tag` | Docker image tag for ECS task definitions | `latest` |
| `ecs_web_ui_cpu` | CPU units for web-ui Fargate task (256 = 0.25 vCPU) | `256` |
| `ecs_web_ui_memory` | Memory (MiB) for web-ui Fargate task | `512` |
| `ecs_media_worker_cpu` | CPU units for media-worker Fargate task | `512` |
| `ecs_media_worker_memory` | Memory (MiB) for media-worker Fargate task | `1024` |
| `ecs_video_worker_cpu` | CPU units for video-worker Fargate task (thin client) | `512` |
| `ecs_video_worker_memory` | Memory (MiB) for video-worker Fargate task | `1024` |
| `ecs_video_worker_min_capacity` | Minimum video-worker tasks | `0` |
| `ecs_video_worker_max_capacity` | Maximum video-worker tasks | `8` |
| `inference_backend` | Inference backend: `sagemaker` (managed endpoint) or `http` (your own inference server URL) | `sagemaker` |
| `inference_http_url` | When `inference_backend=http`, URL of your inference server (e.g. `http://10.0.1.5:8080`). You run the inference service yourself (SageMaker, your own EC2, etc.). | (empty) |
| `sagemaker_instance_type` | SageMaker endpoint instance type (e.g. ml.g4dn.xlarge) | `ml.g4dn.xlarge` |
| `sagemaker_instance_count` | Number of instances for the SageMaker endpoint | `1` |
| `codebuild_stereocrafter_repo_url` | Git repo URL for CodeBuild to clone (stereocrafter-sagemaker) | `https://github.com/alexpialetski/stereo-spot.git` |

## Resources

### S3

- **Input bucket** (`stereo-spot-input-<account_id>`): User uploads to `input/{job_id}/source.mp4`; media-worker writes segments to `segments/{job_id}/...`. No lifecycle rule on this bucket.
- **Output bucket** (`stereo-spot-output-<account_id>`): The inference side (SageMaker or HTTP server) writes segment outputs to `jobs/{job_id}/segments/{segment_index}.mp4`; S3 notifies the segment-output queue and the video-worker writes SegmentCompletion. Media-worker writes `jobs/{job_id}/final.mp4`. **Lifecycle rule**: objects under prefix `jobs/` that are **tagged** with `stereo-spot-lifecycle = expire-segments` expire after **1 day**. Segment outputs should be tagged by the inference container; `final.mp4` is not tagged and is retained.

### S3 event notifications (input bucket → SQS)

Two event flows are configured on the **input bucket** (S3 → SQS direct, no Lambda):

1. **Full-file upload → chunking queue**  
   Prefix `input/`, suffix `.mp4` → **chunking queue**. When the user uploads to `input/{job_id}/source.mp4`, S3 sends the event (bucket, key) to the chunking queue; the media-worker consumes it and runs ffmpeg chunking.

2. **Segment upload → video-worker queue**  
   Prefix `segments/`, suffix `.mp4` → **video-worker queue**. When the media-worker uploads segment files to `segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4`, S3 sends the event to the video-worker queue; the video-worker consumes it and runs inference.

Queue policies allow the input bucket to send messages to the chunking and video-worker queues. Workers consume raw S3 events and use **SQS long polling** (default 20s wait) for responsive pickup; optional env `SQS_LONG_POLL_WAIT_SECONDS` (0–20) can be set in the task definition if needed.

### S3 event notifications (output bucket → SQS)

One event flow is configured on the **output bucket**:

- **Segment output → segment-output queue**  
  Prefix `jobs/`, suffix `.mp4` → **segment-output queue**. When the inference side (SageMaker or HTTP server) writes a segment to `jobs/{job_id}/segments/{segment_index}.mp4`, S3 sends the event to the segment-output queue; the video-worker (segment-output consumer) writes the SegmentCompletion record to DynamoDB. Keys like `jobs/{job_id}/final.mp4` are ignored by the consumer (parser returns None).

### SQS

- **Chunking queue** + **chunking DLQ** (redrive after `dlq_max_receive_count`).
- **Video-worker queue** + **video-worker DLQ**.
- **Segment-output queue** + **segment-output DLQ** (output bucket S3 events; video-worker consumes and writes SegmentCompletion).
- **Reassembly queue** + **reassembly DLQ**.

Visibility timeouts: chunking 15 min, video-worker 10 min (worker only invokes async and polls for response), segment-output 2 min, reassembly 10 min.

The video-worker task receives **SEGMENT_OUTPUT_QUEUE_URL** (Terraform output `segment_output_queue_url`) and consumes both the video-worker queue and the segment-output queue in two threads.

### DynamoDB

- **Jobs**: PK `job_id` (String). GSI `status-completed_at`: PK `status`, SK `completed_at` (Number) for list completed jobs. GSI `status-created_at`: PK `status`, SK `created_at` (Number) for list in-progress jobs.
- **SegmentCompletions**: PK `job_id`, SK `segment_index`. Query by `job_id` returns segments in order for reassembly.
- **ReassemblyTriggered**: PK `job_id`. TTL enabled on attribute `ttl` (e.g. set to `triggered_at + 90 days` by Lambda/worker).

### CloudWatch

- **DLQ alarms**: One alarm per DLQ (`ApproximateNumberOfMessagesVisible > 0`, 1 evaluation period). Alarms are named so the queue is identifiable (chunking-dlq, video-worker-dlq, segment-output-dlq, reassembly-dlq). When any message is in a DLQ, the alarm fires for failed-message visibility. Optional: add an SNS topic for notifications (follow-up).

## Access patterns

1. **List completed jobs**: Query Jobs GSI `status-completed_at` with `status = 'completed'`, `ScanIndexForward = false`, pagination via `Limit` and `ExclusiveStartKey`.
2. **List in-progress jobs**: Query Jobs GSI `status-created_at` for `status` in (created, chunking_in_progress, chunking_complete), merge and sort by `created_at` desc.
3. **Get/update job by job_id**: GetItem / UpdateItem on Jobs.
4. **Query SegmentCompletions by job_id**: Query with PK `job_id`, ordered by `segment_index`.
5. **Conditional write to ReassemblyTriggered by job_id**: PutItem with condition (e.g. item must not exist) for idempotency.

## ECS cluster, task definitions, services, ALB

- **VPC**: Private and public subnets; Fargate tasks run in private subnets, ALB in public subnets.
- **ECS cluster**: Single cluster (`stereo-spot`) with Fargate and EC2 capacity.
- **ECR**: One repository per image: `stereo-spot-web-ui`, `stereo-spot-media-worker`, `stereo-spot-video-worker`, `stereo-spot-stereocrafter-sagemaker`.
- **Task definitions**: `web-ui`, `media-worker`, `video-worker`. Each has container definition with image (ECR URL + `ecs_image_tag`), environment variables from Terraform, and IAM **task role**. Web-ui exposes port 8000. **Video-worker** runs on Fargate (no GPU); it has `INFERENCE_BACKEND=sagemaker`, `SAGEMAKER_ENDPOINT_NAME`, `SAGEMAKER_REGION`, `VIDEO_WORKER_QUEUE_URL`, and **`SEGMENT_OUTPUT_QUEUE_URL`** set by Terraform (consumes both queues in two threads).
- **Task roles**: One IAM role per workload. Video-worker role includes **sagemaker:InvokeEndpoint** on the StereoCrafter endpoint. A shared **execution role** is used for image pull and CloudWatch Logs.
- **Services**: **web-ui** (Fargate, 1 task, ALB); **media-worker** (Fargate, scale on chunking queue); **video-worker** (Fargate, scale on video-worker queue).
- **CodeBuild**: Project `stereo-spot-stereocrafter-build` clones the public repo, builds the stereocrafter-sagemaker Docker image, and pushes to ECR. Trigger via `nx run stereocrafter-sagemaker:sagemaker-build`.
- **SageMaker**: Model (custom container from ECR stereocrafter-sagemaker image), endpoint configuration (GPU instance type), endpoint. The container receives `HF_TOKEN_ARN` (Secrets Manager) and downloads weights from Hugging Face at startup.
- **Secrets Manager**: Secret `stereo-spot/hf-token` for the Hugging Face token; set the value manually after first apply.
- **ALB**: Application Load Balancer in public subnets; listener HTTP 80 forwards to web-ui target group.

## Order of operations (deploy pipeline)

1. **Create Hugging Face token secret (one-time)** — Terraform creates a Secrets Manager secret `stereo-spot/hf-token` with a placeholder. Set your real Hugging Face token: `aws secretsmanager put-secret-value --secret-id <secret_id_from_output> --secret-string '{"token":"hf_xxx"}'`. See output `hf_token_secret_arn`.
2. **Terraform apply** — Provisions data plane (S3, SQS, DynamoDB, Lambda, S3 events), compute (VPC, ECS cluster, task definitions, services, ALB, ECR, task roles), **SageMaker** (model, endpoint config, endpoint), and **Secrets Manager** secret. Video-worker runs on **Fargate** and uses the SageMaker endpoint for inference.
3. **Build and push images** — Build web-ui, media-worker, video-worker, and push to ECR. For **stereocrafter-sagemaker**: `nx run stereocrafter-sagemaker:sagemaker-build` triggers AWS CodeBuild to build the image and push to ECR; `nx run stereocrafter-sagemaker:sagemaker-deploy` updates the SageMaker endpoint to use it (run only when you want to roll the endpoint). For web-ui, media-worker, video-worker: `nx run-many -t deploy` (requires `nx run aws-infra:ecr-login` first). The SageMaker endpoint will pull the inference image from the `stereocrafter-sagemaker` ECR repo. If the inference image does not exist yet, the endpoint may show Failed until CodeBuild pushes it.
4. **Deploy ECS** — `nx run aws-infra:ecr-login` (if needed), then `nx run-many -t deploy` to build, push, and force new deployment for web-ui, media-worker, video-worker.

**Verification:** After apply: `aws ecs list-services --cluster <ecs_cluster_name>`, `aws ecs describe-services --cluster <ecs_cluster_name> --services web-ui media-worker video-worker`. Access web-ui via the ALB DNS name (output `web_ui_url` or `web_ui_alb_dns_name`). SageMaker endpoint name is in output `sagemaker_endpoint_name` (video-worker task env is set by Terraform).

## Scaling

- **Media-worker** scales on chunking queue depth (Application Auto Scaling). Min 0, max 10.
- **Video-worker** scales on video-worker queue depth (same pattern). Min/max set by `ecs_video_worker_min_capacity` and `ecs_video_worker_max_capacity`. Video-worker runs on **Fargate** (thin client); GPU inference runs on the **SageMaker** endpoint. Set the video-worker SQS **visibility timeout** to at least 2–3× the expected segment processing time (e.g. 15–20 minutes).
- **SageMaker** endpoint uses the instance type and count from variables (`sagemaker_instance_type`, `sagemaker_instance_count`). Scale the endpoint or use SageMaker Serverless if needed.

## Outputs

See `outputs.tf`. Outputs expose: data plane (buckets, queue URLs, table names), ECS/ECR (`ecr_web_ui_url`, `ecr_media_worker_url`, `ecr_video_worker_url`, `ecr_stereocrafter_sagemaker_url`), **CodeBuild** (`codebuild_project_name`), **SageMaker** (`sagemaker_endpoint_name`, `sagemaker_endpoint_role_arn`, `sagemaker_instance_type`, `sagemaker_instance_count`), **HTTP inference** when `inference_backend=http` (`inference_http_url`), **Secrets Manager** (`hf_token_secret_arn`), and **region** (`region`). Use `nx run aws-infra:terraform-output` to write them to `packages/aws-infra/.env`.

## Running Terraform

Ensure AWS credentials and region are set (e.g. via `.env` and your environment or Nx). Then:

```bash
nx run aws-infra-setup:terraform-init   # if backend not yet created
nx run aws-infra:terraform-init
nx run aws-infra:terraform-plan
nx run aws-infra:terraform-apply        # after reviewing plan
```

After apply: `aws s3 ls`, `aws sqs list-queues`, `aws dynamodb list-tables`, `aws ecs list-services --cluster <ecs_cluster_name>`, and open `http://<web_ui_alb_dns_name>` to verify.
