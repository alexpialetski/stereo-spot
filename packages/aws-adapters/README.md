# stereo-spot-aws-adapters

AWS implementations of the stereo-spot cloud interfaces defined in **shared-types**: JobStore, SegmentCompletionStore, QueueSender/QueueReceiver, and ObjectStorage. This package keeps shared-types cloud-agnostic; applications and workers depend on shared-types and wire in AWS backends via this package (e.g. `STORAGE_ADAPTER=aws` and required env vars).

## Implementations

| Interface | Implementation | Backend |
|-----------|----------------|--------|
| JobStore | DynamoDBJobStore | DynamoDB Jobs table + GSI `status-completed_at` |
| SegmentCompletionStore | DynamoSegmentCompletionStore | DynamoDB SegmentCompletions table |
| QueueSender / QueueReceiver | SQSQueueSender / SQSQueueReceiver | SQS |
| ObjectStorage | S3ObjectStorage | S3 presign and upload/download |

Resource names (table names, queue URLs, bucket names) are **not** hardcoded: they are passed at construction time, typically from **environment variables** that match Terraform outputs.

## Configuration and environment variables

When running against AWS (or LocalStack), set the following. Names align with Terraform outputs from **packages/aws-infra** (snake_case Terraform outputs are typically exposed as env vars in UPPER_SNAKE_CASE).

| Env var | Description | Terraform output |
|---------|-------------|------------------|
| `INPUT_BUCKET_NAME` | S3 input bucket (source uploads, segment files) | `input_bucket_name` |
| `OUTPUT_BUCKET_NAME` | S3 output bucket (segment outputs, final.mp4) | `output_bucket_name` |
| `JOBS_TABLE_NAME` | DynamoDB Jobs table | `jobs_table_name` |
| `SEGMENT_COMPLETIONS_TABLE_NAME` | DynamoDB SegmentCompletions table | `segment_completions_table_name` |
| `CHUNKING_QUEUE_URL` | SQS chunking queue URL | `chunking_queue_url` |
| `VIDEO_WORKER_QUEUE_URL` | SQS video-worker queue URL | `video_worker_queue_url` |
| `REASSEMBLY_QUEUE_URL` | SQS reassembly queue URL | `reassembly_queue_url` |
| `AWS_REGION` | (Optional) AWS region | — |
| `AWS_ENDPOINT_URL` | (Optional) Override endpoint (e.g. LocalStack) | — |

### Wiring implementations

**Option 1 — From env (recommended for ECS tasks and Lambda):** Use the helpers in `stereo_spot_aws_adapters.env_config` so Terraform outputs (injected as env vars) drive configuration:

```python
from stereo_spot_aws_adapters.env_config import (
    job_store_from_env,
    segment_completion_store_from_env,
    object_storage_from_env,
    input_bucket_name,
    output_bucket_name,
    chunking_queue_receiver_from_env,
)

job_store = job_store_from_env()
segment_store = segment_completion_store_from_env()
storage = object_storage_from_env()
input_bucket = input_bucket_name()
output_bucket = output_bucket_name()
chunking_receiver = chunking_queue_receiver_from_env()
```

**Option 2 — Explicit construction:** Pass table names, queue URLs, and region/endpoint explicitly (e.g. from config file or flags):

```python
from stereo_spot_aws_adapters import (
    DynamoDBJobStore,
    DynamoSegmentCompletionStore,
    S3ObjectStorage,
    SQSQueueReceiver,
)

job_store = DynamoDBJobStore("my-stack-jobs", region_name="us-east-1")
segment_store = DynamoSegmentCompletionStore("my-stack-segment-completions", region_name="us-east-1")
storage = S3ObjectStorage(region_name="us-east-1")
receiver = SQSQueueReceiver("https://sqs.us-east-1.amazonaws.com/123/chunking")
```

## Consumers

Packages that use **aws-adapters** for AWS backends:

- **web-ui** — JobStore, ObjectStorage (presign upload/playback, list completed jobs)
- **media-worker** — JobStore, ObjectStorage, QueueReceiver (chunking queue), QueueReceiver (reassembly queue), SegmentCompletionStore, ReassemblyTriggeredLock
- **video-worker** — QueueReceiver (video-worker queue), ObjectStorage, SegmentCompletionStore

## Installation and tests

From the monorepo root, install **shared-types** first, then this package:

```bash
pip install -e packages/shared-types
pip install -e packages/aws-adapters
# With dev deps (pytest, moto) for tests:
pip install -e "packages/aws-adapters[dev]"
```

Run tests (uses **moto** to mock DynamoDB, SQS, S3):

```bash
nx run aws-adapters:test
```

Lint:

```bash
nx run aws-adapters:lint
```

## No Docker image

This package is a Python library only; it is not built into a Docker image. It is consumed by web-ui, media-worker, and video-worker, which are the components that get containerized and deployed.
