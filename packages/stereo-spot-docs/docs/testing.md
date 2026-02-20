---
sidebar_position: 4
---

# Testing

Unit tests, integration tests, and a data-plane smoke test. The smoke test runs against your **deployed data plane** (e.g. after Terraform apply); see the AWS section for how to get Terraform outputs.

## Install dependencies (once)

All Python lint, test, and run targets depend on **`stereo-spot:install-deps`**. Nx runs it automatically before any dependent target. It installs all Python packages in editable mode with **`[dev]`** extras (ruff, pytest, moto, etc.) so lint and test have the tools they need. To run it explicitly:

```bash
nx run stereo-spot:install-deps
```

## Unit tests

- **shared-types:** `nx run shared-types:test` (pytest; no cloud)
- **aws-adapters:** `nx run aws-adapters:test` (pytest with moto; no real AWS)
- **stereo-inference:** `nx run stereo-inference:test` (pytest; facades/adapters; no real AWS)
- **web-ui, media-worker, video-worker:** `nx run <project>:test`
- **All:** `nx run-many -t test`

Unit tests do not require cloud credentials. aws-adapters tests use **moto** to mock DynamoDB, SQS, and S3.

## Integration tests

The **integration** package runs the full pipeline against **moto** (no real cloud or LocalStack).

**What they cover:**

1. **E2E pipeline:** Create job via API → upload source → chunking → video-worker (stub) → reassembly trigger (simulated) → reassembly → Job completed and final file exists.
2. **Reassembly idempotency:** Two reassembly messages for the same job_id → exactly one reassembly run produces the final file; the other skips.

**Prerequisites:** **ffmpeg** on `PATH` (E2E/idempotency tests are skipped if not found). No cloud credentials.

```bash
nx run integration:test
```

## Data-plane smoke test

Validates the data plane (object storage, queues, job store) end-to-end using **real** resources (or LocalStack). No workers run; only SDK/API calls.

**What it does:**

1. Creates a job in the job store.
2. Sends one message to each main queue with a minimal valid payload.
3. Verifies presigned upload and download for the standard keys (e.g. input and final paths).

**Prerequisites:**

- Infra has been applied (buckets, queues, tables exist).
- An env file exists with resource names/URLs (e.g. from your Terraform output step).
- Credentials configured with permission to read/write those resources.

**How to run:** From the repo root, run the smoke-test target for your adapters package (e.g. `nx run aws-adapters:smoke-test`). It loads the env file from your infra package. See the AWS section for obtaining Terraform outputs.

**LocalStack:** Point adapters at LocalStack via the appropriate endpoint env var and use an env file with LocalStack resource names/URLs.
