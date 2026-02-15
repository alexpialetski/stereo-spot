# Terraform Module: aws-infra

This module provisions the **data plane** and **compute plane** for stereo-spot: S3 buckets, SQS queues (with DLQs), DynamoDB tables, CloudWatch alarms, **S3 event notifications** (S3 → SQS), **ECS cluster**, **ECR** repositories, **task definitions** and **ECS services** (Fargate for web-ui and media-worker, EC2 for video-worker with GPU), **ALB** for web-ui, and **IAM task roles**. It uses the AWS S3 backend from the `aws-infra-setup` project.

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
| `ecs_video_worker_cpu` | CPU units for video-worker EC2 task | `4096` |
| `ecs_video_worker_memory` | Memory (MiB) for video-worker EC2 task | `16384` |
| `ecs_video_worker_min_capacity` | Minimum video-worker tasks | `0` |
| `ecs_video_worker_max_capacity` | Maximum video-worker tasks (GPU capacity) | `8` |

## Resources

### S3

- **Input bucket** (`stereo-spot-input-<account_id>`): User uploads to `input/{job_id}/source.mp4`; media-worker writes segments to `segments/{job_id}/...`. No lifecycle rule on this bucket.
- **Output bucket** (`stereo-spot-output-<account_id>`): Video-worker writes `jobs/{job_id}/segments/{segment_index}.mp4`; media-worker writes `jobs/{job_id}/final.mp4`. **Lifecycle rule**: objects under prefix `jobs/` that are **tagged** with `stereo-spot-lifecycle = expire-segments` expire after **1 day**. The video-worker must tag segment outputs with this tag; `final.mp4` is not tagged and is retained.

### S3 event notifications (input bucket → SQS)

Two event flows are configured on the **input bucket** (S3 → SQS direct, no Lambda):

1. **Full-file upload → chunking queue**  
   Prefix `input/`, suffix `.mp4` → **chunking queue**. When the user uploads to `input/{job_id}/source.mp4`, S3 sends the event (bucket, key) to the chunking queue; the media-worker consumes it and runs ffmpeg chunking.

2. **Segment upload → video-worker queue**  
   Prefix `segments/`, suffix `.mp4` → **video-worker queue**. When the media-worker uploads segment files to `segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4`, S3 sends the event to the video-worker queue; the video-worker consumes it and runs inference.

Queue policies allow the input bucket to send messages to the chunking and video-worker queues. Workers already consume raw S3 events; no code changes required.

### SQS

- **Chunking queue** + **chunking DLQ** (redrive after `dlq_max_receive_count`).
- **Video-worker queue** + **video-worker DLQ**.
- **Reassembly queue** + **reassembly DLQ**.

Visibility timeouts: chunking 15 min, video-worker 20 min, reassembly 10 min.

### DynamoDB

- **Jobs**: PK `job_id` (String). GSI `status-completed_at`: PK `status`, SK `completed_at` (Number) for "list completed jobs" (query `status = 'completed'`, descending by `completed_at`, pagination via `ExclusiveStartKey`).
- **SegmentCompletions**: PK `job_id`, SK `segment_index`. Query by `job_id` returns segments in order for reassembly.
- **ReassemblyTriggered**: PK `job_id`. TTL enabled on attribute `ttl` (e.g. set to `triggered_at + 90 days` by Lambda/worker).

### CloudWatch

- **DLQ alarms**: One alarm per DLQ (`ApproximateNumberOfMessagesVisible > 0`, 1 evaluation period). Alarms are named so the queue is identifiable (chunking-dlq, video-worker-dlq, reassembly-dlq). When any message is in a DLQ, the alarm fires for failed-message visibility. Optional: add an SNS topic for notifications (follow-up).

## Access patterns

1. **List completed jobs**: Query Jobs GSI `status-completed_at` with `status = 'completed'`, `ScanIndexForward = false`, pagination via `Limit` and `ExclusiveStartKey`.
2. **Get/update job by job_id**: GetItem / UpdateItem on Jobs.
3. **Query SegmentCompletions by job_id**: Query with PK `job_id`, ordered by `segment_index`.
4. **Conditional write to ReassemblyTriggered by job_id**: PutItem with condition (e.g. item must not exist) for idempotency.

## ECS cluster, task definitions, services, ALB

- **VPC**: Private and public subnets; Fargate tasks run in private subnets, ALB in public subnets.
- **ECS cluster**: Single cluster (`stereo-spot`) with Fargate and EC2 capacity.
- **ECR**: One repository per image: `stereo-spot-web-ui`, `stereo-spot-media-worker`, `stereo-spot-video-worker`.
- **Task definitions**: `web-ui`, `media-worker`, `video-worker`. Each has container definition with image (ECR URL + `ecs_image_tag`), environment variables (bucket names, table names, queue URLs, `AWS_REGION`) from Terraform, and IAM **task role** for AWS API access. Web-ui exposes port 8000; video-worker has GPU requirement (`resourceRequirements`).
- **Task roles**: One IAM role per workload (web-ui: S3 + DynamoDB Jobs; media-worker: S3 + DynamoDB + SQS chunking/reassembly; video-worker: S3 + DynamoDB SegmentCompletions + SQS video-worker). ECS tasks assume these via `task_role_arn`. A shared **execution role** is used for image pull and CloudWatch Logs.
- **Services**:
  - **web-ui**: Fargate, desired count 1, ALB in front (HTTP 80 → target group port 8000).
  - **media-worker**: Fargate, desired count 0 (scaled by Application Auto Scaling on chunking queue depth).
  - **video-worker**: EC2 launch type, desired count 0 (scaled by Application Auto Scaling on video-worker queue depth). Requires EC2 capacity with GPU (see below).
- **ALB**: Application Load Balancer in public subnets; listener HTTP 80 forwards to web-ui target group.

## Order of operations (deploy pipeline)

1. **Terraform apply** — Provisions data plane (S3, SQS, DynamoDB, Lambda, S3 events) and compute (VPC, ECS cluster, task definitions, services, ALB, ECR, task roles).
2. **Build and push images** — Build web-ui, media-worker, video-worker Docker images; push to ECR with the tag you use for `ecs_image_tag` (e.g. `latest` or git SHA).
3. **Deploy** — Update ECS services to use the new image: `aws ecs update-service --cluster <ecs_cluster_name> --service web-ui --force-new-deployment` (and similarly for media-worker, video-worker). Alternatively, set variable `ecs_image_tag` and re-run Terraform to create a new task definition revision; then force new deployment so services pick it up.

**Verification:** After apply: `aws ecs list-services --cluster <ecs_cluster_name>`, `aws ecs describe-services --cluster <ecs_cluster_name> --services web-ui media-worker video-worker`. Access web-ui via the ALB DNS name (output `web_ui_url` or `web_ui_alb_dns_name`).

## Scaling and GPU (video-worker EC2)

- **Media-worker** scales on chunking queue depth (Application Auto Scaling with custom metric `AWS/SQS` `ApproximateNumberOfMessagesVisible`). Min 0, max 10.
- **Video-worker** scales on video-worker queue depth (same pattern). Min/max set by `ecs_video_worker_min_capacity` and `ecs_video_worker_max_capacity`.
- **Video-worker** runs on **EC2** with GPU. To enable it you must add **EC2 capacity** to the ECS cluster: create an **Auto Scaling group** with GPU instance types (e.g. g4dn.xlarge, g5.xlarge), ECS-optimized AMI (with GPU support), and IAM instance profile that allows ECS (e.g. `AmazonEC2ContainerServiceforEC2Role`). Register the ASG as an ECS **capacity provider** and associate it with the cluster; then set the video-worker service to use that capacity provider. Alternatively use a single capacity provider strategy (e.g. FARGATE for CPU workloads and a custom GPU capacity provider for video-worker). Without EC2 GPU capacity, video-worker desired count remains 0 and scaling will only add tasks once capacity is available.

## Outputs

See `outputs.tf`. Outputs expose: data plane (`input_bucket_name`, `output_bucket_name`, queue URLs, table names) and ECS/ECR (`ecs_cluster_name`, `ecs_cluster_arn`, `web_ui_alb_dns_name`, `web_ui_url`, `ecr_web_ui_url`, `ecr_media_worker_url`, `ecr_video_worker_url`). Use `nx run aws-infra:terraform-output` to write them to `terraform-outputs.env` (or consume via Terraform output in CI).

## Running Terraform

Ensure AWS credentials and region are set (e.g. via `.env` and your environment or Nx). Then:

```bash
nx run aws-infra-setup:terraform-init   # if backend not yet created
nx run aws-infra:terraform-init
nx run aws-infra:terraform-plan
nx run aws-infra:terraform-apply        # after reviewing plan
```

After apply: `aws s3 ls`, `aws sqs list-queues`, `aws dynamodb list-tables`, `aws ecs list-services --cluster <ecs_cluster_name>`, and open `http://<web_ui_alb_dns_name>` to verify.
