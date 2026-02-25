---
sidebar_position: 2
---

# AWS services and requirements

How each generic requirement maps to an AWS service in the current implementation.

| Requirement | AWS service | How it fulfils the need |
|-------------|-------------|--------------------------|
| **Compute (web, workers)** | **ECS Fargate** | Web-ui, media-worker, video-worker run as ECS services. No server management; scale by queue depth (Application Auto Scaling). |
| **Object storage** | **S3** | Input bucket (upload source, segment files); output bucket (segment outputs, final.mp4). Presigned URLs for upload and playback. |
| **Queues** | **SQS** | Chunking, video-worker, output-events, reassembly queues. S3 event notifications feed chunking and video-worker queues; output bucket feeds output-events (segment files and SageMaker async results). |
| **Job / segment state** | **DynamoDB** | Jobs table (PK job_id; GSIs for list completed / in-progress). SegmentCompletions (PK job_id, SK segment_index). ReassemblyTriggered (PK job_id) for trigger idempotency and reassembly lock. |
| **Inference** | **SageMaker** or **HTTP** | Default: SageMaker async endpoint (GPU, e.g. ml.g4dn) for iw3. Alternative: HTTP URL (your own inference server). |
| **Container registry** | **ECR** | One repo per image: web-ui, media-worker, video-worker, stereo-inference. ECS and SageMaker pull from ECR. |
| **Inference image build** | **CodeBuild** | stereo-inference image: CodeBuild clones repo, docker build, push to ECR. Triggered by `nx run stereo-inference:inference-build`. |
| **Load balancing** | **ALB** | Web-ui ECS service behind ALB; HTTPS to the dashboard and API. |

All workloads use **IAM task roles**; no long-lived credentials in config.
