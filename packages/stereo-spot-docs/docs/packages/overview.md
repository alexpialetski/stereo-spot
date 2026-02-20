---
sidebar_position: 1
---

# Packages overview

Per-package purpose, main Nx targets, and how each fits in the pipeline. Single source for this narrative; in-repo package READMEs are minimal stubs with a link here.

**On this page:** [web-ui](#web-ui) · [media-worker](#media-worker) · [video-worker](#video-worker) · [stereo-inference](#stereo-inference) · [shared-types](#shared-types) · [aws-adapters](#aws-adapters) · [aws-infra-setup](#aws-infra-setup) · [aws-infra](#aws-infra) · [analytics](#analytics) · [integration](#integration)

## web-ui

**Purpose:** FastAPI server-rendered UI: dashboard, job creation (form POST → redirect with upload URL), unified jobs list (in-progress + completed), job detail with upload form or video player + download, live progress via SSE.

**Main targets:** `serve`, `test`, `lint`, `build` (Docker), `deploy` (push image + ECS force-new-deployment).

**Env (when using aws-adapters):** `INPUT_BUCKET_NAME`, `OUTPUT_BUCKET_NAME`, `JOBS_TABLE_NAME`, `SEGMENT_COMPLETIONS_TABLE_NAME`, `AWS_REGION`; optional `AWS_ENDPOINT_URL` (e.g. LocalStack). Local: `STEREOSPOT_ENV_FILE` to load from file.

**Dependencies:** shared-types, aws-adapters. Uses JobStore and ObjectStorage abstractions.

---

## media-worker

**Purpose:** Single package for CPU/ffmpeg work: **chunking** (split source, upload segments) and **reassembly** (concat segment outputs to final file). Consumes chunking queue and reassembly queue (two threads in one process).

**Main targets:** `test`, `lint`, `build` (Docker), `deploy`.

**Env:** Job store, segment-completion store, queue receiver (chunking + reassembly), object storage (input/output buckets). See aws-adapters for AWS env vars.

**Dependencies:** shared-types, aws-adapters. Writes segment keys in canonical format; updates job to chunking_complete; builds concat list from SegmentCompletions.

---

## video-worker

**Purpose:** Coordinator: consumes video-worker queue and segment-output queue. Invokes inference (stub, SageMaker, or HTTP). After each SegmentCompletion put, runs reassembly trigger (conditional create + send to reassembly queue).

**Main targets:** `test`, `lint`, `build` (Docker), `deploy`.

**Env:** Queues, job store, segment-completion store, reassembly queue sender; inference endpoint name or HTTP URL, region. See AWS section for SageMaker/HTTP vars.

**Dependencies:** shared-types, aws-adapters. Uses segment key parser from shared-types; writes SegmentCompletions; triggers reassembly when last segment completes.

---

## stereo-inference

**Purpose:** Custom inference container (e.g. iw3/nunif: 2D→stereo SBS/anaglyph). Used by SageMaker or run as HTTP server. Storage and metrics are adapter-based.

**Main targets:** `test`, `lint`, `sagemaker-build` (trigger CodeBuild), `sagemaker-deploy` (update SageMaker endpoint). When `inference_backend=http`, you run your own server.

**Env (in container):** Storage and metrics provider; optional `IW3_LOW_VRAM=1` for smaller GPUs.

**Dependencies:** shared-types (segment key parsing). No aws-adapters in image; uses storage adapter (S3/GCS) and optional metrics.

---

## shared-types

**Purpose:** Python library: Pydantic models for Job, queue payloads, segment key format, SegmentCompletion, API DTOs. Single source of truth; no Docker image.

**Main targets:** `test`, `lint`.

**Consumers:** web-ui, media-worker, video-worker, aws-adapters, stereo-inference (key parsing). All depend on it via Nx graph; `stereo-spot:install-deps` installs it in editable mode.

---

## aws-adapters

**Purpose:** AWS implementations of JobStore, SegmentCompletionStore, QueueSender/Receiver, ObjectStorage (DynamoDB, SQS, S3). Used when `STORAGE_ADAPTER=aws` or equivalent.

**Main targets:** `test` (pytest with moto), `lint`, `smoke-test` (data-plane e2e against real AWS or LocalStack).

**Env (smoke-test and production):** Bucket names, table names, queue URLs; `AWS_REGION`; optional `AWS_ENDPOINT_URL`. Load from `terraform-outputs.env` or equivalent.

**Dependencies:** shared-types.

---

## aws-infra-setup

**Purpose:** Terraform backend: S3 bucket for state, DynamoDB table for locking. Uses nx-terraform; linked to aws-infra.

**Main targets:** `terraform-init`, `terraform-plan`, `terraform-apply`, `terraform-destroy`, `terraform-output`.

---

## aws-infra

**Purpose:** Terraform: S3, SQS, DynamoDB, ECS cluster, ECR, CodeBuild (stereo-inference build), task definitions and services (Fargate), SageMaker or HTTP inference, ALB. Backend dependency on aws-infra-setup.

**Main targets:** Same Terraform targets; `terraform-output` exports resource names/URLs to env file for workers and smoke-test.

---

## analytics

**Purpose:** Gather conversion metrics from CloudWatch (AWS) or future cloud monitoring. Optional; not required for the pipeline.

**Main targets:** `gather` (with configs: aws, gcp), `test`, `lint`.

**Dependencies:** shared-types; uses Terraform outputs for env (e.g. aws-infra).

---

## integration

**Purpose:** End-to-end and integration tests against **moto** (no real cloud). E2E pipeline and reassembly idempotency.

**Main targets:** `test`. Requires ffmpeg on PATH for full E2E.

**Dependencies:** shared-types, aws-adapters, web-ui, media-worker, video-worker (editable install via install-deps).
