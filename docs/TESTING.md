# Testing

This document describes how to run unit tests, the data-plane smoke test, and integration tests.

## Python editable deps (install once)

All Python test and run targets that use monorepo packages depend on **`stereo-spot:install-deps`**. That target installs shared-types, aws-adapters, web-ui, media-worker, video-worker, analytics, and integration in editable mode from the workspace root. Nx runs it automatically before any dependent target (e.g. when you run a test), so you do not need to run it manually unless you want to refresh the env (e.g. after pulling or changing dependencies). To run it explicitly:

```bash
nx run stereo-spot:install-deps
```

Then run tests or other targets as below.

## Unit tests

- **shared-types:** `nx run shared-types:test` (pytest; no monorepo deps)
- **aws-adapters:** `nx run aws-adapters:test` (pytest with moto; no real AWS)
- **stereo-inference:** `nx run stereo-inference:test` (pytest; storage/metrics/serve facades and adapters; no real AWS)
- **web-ui, media-worker, video-worker:** `nx run <project>:test`
- Run all tests: `nx run-many -t test`

Unit tests do not require AWS credentials. aws-adapters tests use **moto** to mock DynamoDB, SQS, and S3.

## Integration tests (Step 5.1)

The **`packages/integration`** package contains end-to-end and integration tests that run the full pipeline against **moto** (no real AWS or LocalStack).

**What they cover:**

1. **E2E pipeline:** Create job via API → upload source → chunking → video-worker (stub) → reassembly trigger (simulated) → reassembly → Job completed and `final.mp4` exists.
2. **Reassembly idempotency:** Two reassembly messages for the same job_id → exactly one reassembly run produces `final.mp4`; the other skips (conditional update on ReassemblyTriggered fails) and deletes the message without overwriting.

**Prerequisites:**

- **ffmpeg** on `PATH` (E2E and idempotency tests are skipped if not found).
- No AWS credentials (moto is used).

**How to run:**

```bash
nx run integration:test
```

In CI, run `nx run integration:test` when integration is enabled (e.g. on every PR). Use `nx run-many -t test` to run unit tests for all projects; add `integration:test` to the same workflow or run it when integration is enabled (env or flag).

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
