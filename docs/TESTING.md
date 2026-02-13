# Testing

This document describes how to run unit tests and the data-plane smoke test. For end-to-end and integration tests (Phase 5), see [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Unit tests

- **shared-types:** `nx run shared-types:test` (pytest)
- **aws-adapters:** `nx run aws-adapters:test` (pytest with moto; no real AWS)
- Run all tests: `nx run-many -t test`

Unit tests do not require AWS credentials. aws-adapters tests use **moto** to mock DynamoDB, SQS, and S3.

## Data plane smoke test (Step 2.3)

The smoke test validates the AWS data plane (S3, SQS, DynamoDB) end-to-end using real AWS (or LocalStack). No workers run; it only uses SDK/API calls.

**What it does:**

1. Creates a Job in the DynamoDB Jobs table (put item).
2. Sends one message to each of the three SQS queues (chunking, video-worker, reassembly) with a minimal valid payload.
3. Verifies S3 presigned upload and download for `input/{job_id}/source.mp4` and `jobs/{job_id}/final.mp4`, and performs a small upload/download.

**Prerequisites:**

- Terraform has been applied for **aws-infra** (S3 buckets, SQS queues, DynamoDB tables exist).
- **terraform-outputs.env** exists (e.g. from `nx run aws-infra:terraform-output`), containing: `input_bucket_name`, `output_bucket_name`, `jobs_table_name`, `segment_completions_table_name`, `chunking_queue_url`, `video_worker_queue_url`, `reassembly_queue_url`, and optionally `reassembly_triggered_table_name`.
- AWS credentials configured (environment variables, `~/.aws/credentials`, or profile) with permission to read/write those resources.

**How to run:**

From the repo root:

```bash
nx run aws-adapters:smoke-test
```

This loads `packages/aws-infra/terraform-outputs.env` automatically (keys are uppercased for the adapters). If the env file does not set `AWS_REGION`, it defaults to `us-east-1`. The smoke test creates one Job and one small S3 object; it does not remove them (you can delete the Job and the object manually or leave them).

**Using a custom env file:**

Set `SMOKE_TEST_ENV_FILE` to the path of a key=value file (same shape as terraform-outputs.env):

```bash
SMOKE_TEST_ENV_FILE=/path/to/terraform-outputs.env nx run aws-adapters:smoke-test
```

**LocalStack:**

Point the adapters at LocalStack by setting `AWS_ENDPOINT_URL` (e.g. `http://localhost:4566`) and ensure the env file contains LocalStack resource names/URLs. Run the smoke test the same way.

## Troubleshooting

**`nx run-many -t test` fails with `OSError: No such file or directory: .../__editable__.stereo_spot_shared-0.1.0.pth`**

This happens when pip’s editable install metadata for the monorepo packages is broken (e.g. after a cache restore or parallel installs). Fix it by uninstalling the local packages and re-running tests:

```bash
pip uninstall stereo-spot-shared stereo-spot-aws-adapters -y
nx run-many -t test
```

If failures persist when running all tests in parallel, run tests serially so only one `pip install -e` runs at a time:

```bash
nx run-many -t test --parallel=1
```
