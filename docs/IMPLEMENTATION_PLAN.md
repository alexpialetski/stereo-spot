# Stereo-Spot Implementation Plan

This document provides an **incremental implementation plan** for the stereo-spot application as described in [ARCHITECTURE.md](../ARCHITECTURE.md). Each step is designed to be shippable, with unit tests and documentation. All steps include **Acceptance Criteria (A/C)** and **Verification** instructions.

**Current state:** Phase 1 and Step 2.1–2.3 are done. **packages/shared-types** exists (Pydantic models, segment/input key parsers, cloud abstraction interfaces). **packages/aws-infra-setup** provisions the Terraform S3 backend. **packages/aws-infra** provisions the data plane: two S3 buckets (input, output), three SQS queues + DLQs, three DynamoDB tables (Jobs with GSI, SegmentCompletions, ReassemblyTriggered with TTL), and CloudWatch alarms for each DLQ. **packages/aws-adapters** implements AWS backends for JobStore, SegmentCompletionStore, QueueSender/Receiver, ObjectStorage (exists, upload_file), and ReassemblyTriggeredLock (moto tests, env-based config). Data plane smoke test runs via `nx run aws-adapters:smoke-test` using `packages/aws-infra/.env` (from `nx run aws-infra:terraform-output`). **Step 3.1** is done: **packages/media-worker** (chunking + reassembly in one package/image). **Step 3.2** is done: **packages/video-worker** (stub model, unit tests, README). **Step 3.4** is done: **packages/reassembly-trigger** Lambda. **Step 4.1** is done: **packages/web-ui** FastAPI + Jinja2. **Step 4.2** is done: S3 event notifications (input/ and segments/ → chunking and video-worker queues). **Step 4.3** is done: Compute runs on **ECS** (not EKS). Terraform provisions ECS cluster, task definitions (web-ui, media-worker, video-worker), IAM task roles, Fargate services for web-ui and media-worker, video-worker on **Fargate** (no GPU; invokes SageMaker), ALB, Application Auto Scaling on SQS. **packages/helm** has been removed. Deploy flow: `nx run aws-infra:ecr-login` (when needed), then `nx run-many -t deploy` (build, push to ECR, force ECS deployment). Terraform output is written to `packages/aws-infra/.env`. **Step 5.1** is done: **packages/integration** with E2E pipeline test and reassembly idempotency test; docs/TESTING.md updated. **Step 5.2** is done: **scripts/chunking_recovery.py**, **docs/RUNBOOKS.md**, ARCHITECTURE/IMPLEMENTATION_PLAN cross-links. **Step 5.3** is done: **packages/stereocrafter-sagemaker** (SageMaker custom container with stub handler, contract: s3_input_uri/s3_output_uri); **Secrets Manager** for HF token; Terraform: ECR, SageMaker model/endpoint, video-worker Fargate + InvokeEndpoint; video-worker `INFERENCE_BACKEND=sagemaker` and unit tests. **Step 5.4** (future): replace stub with real StereoCrafter inference and Hugging Face weights at container startup.

**Principles:**

- Implement in dependency order: shared-types → workers & Lambda → web-ui → full AWS (ECS, data plane).
- Add unit tests and markdown docs in the same step as the feature.
- Verify with Nx tasks and automated tests where possible.
- Design and data flow are described in [ARCHITECTURE.md](../ARCHITECTURE.md).

---

## Phase 1: Shared types and conventions

### Step 1.1 — Create `packages/shared-types` Python library skeleton

**Goal:** Add a minimal Python package under `packages/shared-types` that the rest of the pipeline will depend on. No domain models yet; only package layout, build, and test harness.

**Tasks:**

- Create `packages/shared-types/` with `pyproject.toml` (Pydantic dependency, package name e.g. `stereo_spot_shared`), `src/stereo_spot_shared/__init__.py`, and a minimal `README.md`.
- Add Nx project: `project.json` with name `shared-types`, `sourceRoot`, and targets: `build` (e.g. build sdist/wheel or installable), `test` (pytest), `lint` (ruff or similar). Set up pytest and a single placeholder test.
- Document in `packages/shared-types/README.md`: purpose, how to install locally, how to run tests.

**A/C:**

- [x] Package is installable (e.g. `pip install -e packages/shared-types`).
- [x] `nx run shared-types:test` runs and passes (at least one test).
- [x] `packages/shared-types/README.md` describes the package and test commands.

**Verification:**

```bash
cd packages/shared-types && pip install -e . && pytest -v
nx run shared-types:test
```

---

### Step 1.2 — Add Pydantic models and segment key convention to shared-types

**Goal:** Implement the single source of truth for Job, Segment, SegmentCompletion, queue payloads, and API DTOs. Implement the **segment key format and parser** only in this package (used later by media-worker and video-worker).

**Tasks:**

- Add Pydantic models: `Job` (job_id, mode, status, created_at, total_segments, completed_at), `JobStatus`, `StereoMode` (anaglyph | sbs).
- Add `SegmentKeyPayload` (or similar) and a **parser function** that takes `bucket: str, key: str` and returns the canonical segment payload (`job_id`, `segment_index`, `total_segments`, `mode`, `segment_s3_uri`). Key format: `segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4`. Parser must reject invalid keys (raise or return None; document behaviour).
- Add models: `SegmentCompletion`, `ChunkingPayload` (from S3 event: bucket, key; document that job_id/mode come from key + DynamoDB), `VideoWorkerPayload` (job_id, segment_index, total_segments, segment_s3_uri, mode), `ReassemblyPayload` (job_id).
- Add API DTOs: `CreateJobRequest`, `CreateJobResponse`, `JobListItem`, `PresignedPlaybackResponse` (or equivalent).
- Add input key parser: `input/{job_id}/source.mp4` → job_id (for chunking worker).
- Unit tests: (1) segment key build/parse round-trip, (2) invalid segment key rejected, (3) input key parser, (4) serialization/validation of each model (valid and invalid).
- Update `packages/shared-types/README.md` with model summary and key conventions.

**A/C:**

- [x] All models defined in shared-types; segment key parser and input key parser live only here.
- [x] Unit tests cover segment key round-trip, invalid key, input key, and model validation.
- [x] README documents segment key format and parser usage.

**Verification:**

```bash
nx run shared-types:test
# Manually: import and run parser for a sample key; assert payload fields.
```

---

### Step 1.3 — Add cloud abstraction interfaces to shared-types

**Goal:** Define thin interfaces for job store, segment-completion store, queues, and object storage so pipeline logic stays cloud-agnostic. No implementations yet.

**Tasks:**

- Define abstract interfaces (e.g. ABC or Protocol): `JobStore` (get, put, update by job_id; list completed with pagination), `SegmentCompletionStore` (put completion, query by job_id ordered by segment_index), `QueueSender` / `QueueReceiver` (send, receive, delete), `ObjectStorage` (presign upload/download, upload, download).
- Add `docs/SHARED_TYPES.md` (or section in package README) describing each interface and intended usage (e.g. “JobStore is used by web-ui and media-worker”).
- Unit tests: mock implementations of interfaces to satisfy type checkers and one test per interface (e.g. “mock JobStore returns job”).

**A/C:**

- [x] All four abstraction groups (job store, segment-completion store, queues, object storage) defined in shared-types.
- [x] Documentation lists interfaces and consumers.
- [x] Tests prove interfaces can be mocked and used.

**Verification:**

```bash
nx run shared-types:test
```

---

## Phase 2: Core AWS data plane (no EKS yet)

### Step 2.1 — Terraform: S3 buckets, SQS queues, DynamoDB tables

**Goal:** Provision the data plane so workers and web-ui can run against real AWS (or LocalStack) later: input bucket, output bucket, three SQS queues (+ DLQs), Jobs table, SegmentCompletions table, ReassemblyTriggered table with GSI and TTL as per ARCHITECTURE.

**Tasks:**

- In `packages/aws-infra`: add S3 buckets (input, output); S3 lifecycle rule on output bucket for `jobs/*/segments/` (expire after 1 day).
- Add SQS queues: chunking, video-worker, reassembly; each with DLQ and redrive policy (max receive count e.g. 3–5).
- Add DynamoDB: Jobs (PK job_id), SegmentCompletions (PK job_id, SK segment_index), ReassemblyTriggered (PK job_id, TTL on ttl attribute); Jobs GSI `status-completed_at` (PK status, SK completed_at Number).
- For each of the three DLQs, add a **CloudWatch metric alarm**: e.g. `ApproximateNumberOfMessagesVisible > 0` for 1 evaluation period (alarm when any message is in the DLQ). Name or describe alarms so the queue is identifiable (e.g. chunking-dlq, video-worker-dlq, reassembly-dlq). Optionally add an SNS topic for notifications (can be a follow-up).
- Output queue URLs, bucket names, table names from Terraform.
- Document in `packages/aws-infra/README.md` the resources and access patterns (list completed jobs, etc.), and note that DLQ alarms exist in CloudWatch for failed-message visibility.
- No S3 event notifications yet (Step 4.2).

**A/C:**

- [x] `terraform plan` / `apply` creates two S3 buckets, three SQS queues + DLQs, three DynamoDB tables and GSI.
- [x] CloudWatch alarms exist for chunking, video-worker, and reassembly DLQs (e.g. alarm when messages visible > 0).
- [x] Outputs expose bucket names and queue URLs and table names.
- [x] README updated with resource list and access patterns.

**Verification:**

```bash
nx run aws-infra-setup:terraform-init
nx run aws-infra:terraform-init
nx run aws-infra:terraform-plan
# After apply: aws s3 ls; aws sqs list-queues; aws dynamodb list-tables
```

---

### Step 2.2 — AWS implementations in `packages/aws-adapters`

**Goal:** Implement the cloud interfaces for AWS (DynamoDB, SQS, S3) in a **dedicated package** so that shared-types stays cloud-agnostic and app/workers get AWS backends via config. GCP adapters can be added later in a separate package.

**Tasks:**

- Create **`packages/aws-adapters`** with `pyproject.toml` (depends on `shared-types` and `boto3`), Nx `project.json` (name `aws-adapters`, targets: `build` if needed, `test`, `lint`). No Docker image.
- Implement AWS backend for: JobStore (DynamoDB Jobs + GSI query), SegmentCompletionStore (DynamoDB SegmentCompletions), QueueSender/Receiver (SQS), ObjectStorage (S3 presign and upload/download).
- Use Terraform outputs (or env vars) for resource names/URLs; no hardcoding.
- Unit tests: use moto or similar to test DynamoDB/SQS/S3 behaviour; at least one test per store/queue/storage operation.
- Document in `packages/aws-adapters/README.md` how to wire implementations (e.g. `STORAGE_ADAPTER=aws` and required env vars). List which packages consume aws-adapters (web-ui, media-worker, video-worker).

**A/C:**

- [x] All four abstraction interfaces have AWS implementations in `packages/aws-adapters`.
- [x] Unit tests run against moto (or equivalent) and pass.
- [x] Documentation explains configuration and env vars.
- [x] Queue receivers (chunking, video-worker, reassembly) use SQS long polling (default 20s) for responsive message pickup; optional env `SQS_LONG_POLL_WAIT_SECONDS`.

**Verification:**

```bash
nx run aws-adapters:test
```

---

### Step 2.3 — Data plane smoke test

**Goal:** Validate the data plane (S3, SQS, DynamoDB) end-to-end before running full worker pipelines. Reduces risk that integration tests in Phase 5 are the first time everything is wired.

**Tasks:**

- Add a smoke test (e.g. in `packages/integration` created here minimally, or in `packages/aws-adapters`): given AWS credentials and Terraform outputs (or LocalStack), the test (1) creates a Job in DynamoDB (put item), (2) sends one message to each of the three SQS queues (chunking, video-worker, reassembly) with a minimal valid payload, (3) verifies S3 presigned upload and download for input key `input/{job_id}/source.mp4` and output key `jobs/{job_id}/final.mp4`. No workers run; only SDK/API calls.
- Document in `docs/TESTING.md` (or README): how to run the smoke test (env vars or config file with queue URLs, bucket names, table names), and that Terraform must be applied (or LocalStack running) first.

**A/C:**

- [x] Smoke test passes against LocalStack or a test AWS account.
- [x] Documentation explains prerequisites and how to run it.

**Verification:**

```bash
# After Terraform apply: ensure packages/aws-infra/terraform-outputs.env exists (e.g. nx run aws-infra:terraform-output)
nx run aws-adapters:smoke-test
```

---

## Phase 3: Workers and Lambda

### Step 3.1 — Media worker package (chunking + reassembly)

**Goal:** New package `packages/media-worker`: single Docker image that consumes **chunking queue** (raw S3 event) and **reassembly queue** (job_id) in one process (two threads). Chunking: parse input key, ffmpeg split, upload segments, update Job to chunking_complete. Reassembly: lock via ReassemblyTriggered, query SegmentCompletions, ffmpeg concat, upload final.mp4, update Job to completed. Saves storage (one ~600MB image instead of two).

**Tasks:**

- Create `packages/media-worker` with pyproject.toml (depends on shared-types, aws-adapters), Nx project.json (build, test, lint), and Dockerfile (ffmpeg + Python).
- Implement chunking: read S3 event from chunking queue; parse input key via shared-types; get job from JobStore; update job to chunking_in_progress; download source to temp; ffmpeg segment (keyframe-aligned, ~50MB/~5min); upload each segment with canonical key; single UpdateItem for total_segments + status=chunking_complete.
- Implement reassembly: read job_id from reassembly queue; conditional update on ReassemblyTriggered (lock); query SegmentCompletions by job_id; download segments; ffmpeg concat; upload to jobs/{job_id}/final.mp4 (multipart for large files); update Job to completed.
- Run both loops in separate threads from main().
- Unit tests: chunking (S3 event parsing, segment key, mock flow); reassembly (lock, idempotency, concat list, output key, mock flow).
- Add README: purpose, env vars (both queues and all stores), local run, Docker build.

**A/C:**

- [x] Media-worker uses only shared-types for key parsing and key building.
- [x] Unit tests pass for both chunking and reassembly flows (mocked).
- [x] README documents behaviour and how to run.
- [x] Docker image builds from repo root.

**Verification:**

```bash
nx run media-worker:test
nx run media-worker:build   # if Docker build is the “build” target
```

---

### Step 3.2 — Video worker package (stub model first)

**Goal:** New package `packages/video-worker`: consumes video-worker queue (raw S3 event), parses segment payload via shared-types, downloads segment, runs “inference” (stub that copies or no-op for now), uploads output to output bucket, writes SegmentCompletion. Model swappable later.

**Tasks:**

- Create package with dependency on shared-types; use abstractions for queue, ObjectStorage, SegmentCompletionStore.
- Parse S3 event with segment key parser from shared-types; download segment; run stub “model” (e.g. copy input to output or minimal transform); upload to `jobs/{job_id}/segments/{segment_index}.mp4`; put SegmentCompletion.
- Unit tests: (1) segment key parsing from S3 event, (2) output key generation, (3) mock pipeline end-to-end (stub model).
- Add README: design for swapping model (StereoCrafter later), env vars, local run.

**A/C:**

- [x] Video worker uses only shared-types segment key parser; no duplicate parsing.
- [x] Stub model allows pipeline to run without GPU.
- [x] Unit tests pass.

**Verification:**

```bash
nx run video-worker:test
```

---

### Step 3.4 — Reassembly trigger Lambda

**Goal:** Python Lambda in `packages/reassembly-trigger`: DynamoDB Streams handler for SegmentCompletions; for each batch, for each job_id, check Job status=chunking_complete and count(SegmentCompletions)==total_segments; conditional create on ReassemblyTriggered; on success send job_id to reassembly queue.

**Tasks:**

- Create `packages/reassembly-trigger` with handler and Nx project. **Dependency on shared-types:** the Lambda build target must depend on `shared-types:build`. Install shared-types from the **built wheel** (e.g. from Nx build outputs) into the Lambda package directory (e.g. `pip install --no-deps <path-to-wheel>/stereo_spot_shared-*.whl -t ./layer` or equivalent), then zip. Do not use `pip install -e ../shared-types` or raw source in CI—this ensures the Lambda uses the same artifact as other consumers and avoids drift.
- Terraform: Lambda, DynamoDB Stream event source, IAM, SQS send permission.
- Implement idempotent logic: conditional create ReassemblyTriggered; only send to SQS if create succeeded.
- Unit tests: (1) trigger when count matches and job chunking_complete, (2) no trigger when count not reached, (3) no duplicate send when ReassemblyTriggered already exists.
- Document in `packages/reassembly-trigger/README.md`: event shape, how shared-types is bundled from the wheel, Terraform deploy.

**A/C:**

- [x] Lambda triggers reassembly only when last segment completes and job is chunking_complete.
- [x] Conditional create prevents duplicate reassembly messages.
- [x] Lambda deployment package is built from the same shared-types wheel as other consumers (Nx build dependency and install-from-wheel in CI).
- [x] Unit tests pass.

**Verification:**

```bash
nx run reassembly-trigger:test
nx run reassembly-trigger:build
# Terraform apply and manual Stream test (optional in plan).
```

---

## Phase 4: Web UI and orchestration

### Step 4.1 — Web UI package (FastAPI + Jinja2)

**Goal:** New package `packages/web-ui`: FastAPI app, server-rendered pages (Jinja2), job creation (form POST → create job + presigned upload URL, redirect to upload page), list completed jobs (DynamoDB GSI), job detail, presigned playback (redirect or HTML link).

**Tasks:**

- Create package with FastAPI, Jinja2, dependency on shared-types; use JobStore and ObjectStorage abstractions (AWS implementations via config).
- Routes: GET `/`, GET `/jobs`, POST `/jobs` (form: mode), GET `/jobs/{job_id}`, GET `/jobs/{job_id}/play`. Create job: put Job (status=created), generate presigned PUT for `input/{job_id}/source.mp4`, redirect to page showing upload URL and instructions.
- List jobs: query GSI status=completed, descending completed_at, pagination; render HTML. Play: presigned GET for `jobs/{job_id}/final.mp4` (redirect or link).
- Unit tests: (1) create job returns job_id and upload URL with correct key, (2) list endpoint returns only completed, (3) play URL uses correct key.
- Add `packages/web-ui/README.md`: routes, env vars, ECS task role note.

**A/C:**

- [x] All routes from ARCHITECTURE implemented (dashboard, list, create, detail, play).
- [x] Presigned URLs use keys: `input/{job_id}/source.mp4` and `jobs/{job_id}/final.mp4`.
- [x] Unit tests pass.

**Note:** Full browser E2E (upload → chunking → video → reassembly) is only possible after Step 4.2 (S3 event notifications) is in place.

**Verification:**

```bash
nx run web-ui:test
# Optional: run app locally with LocalStack or real AWS and click-through.
```

---

### Step 4.2 — S3 event notifications and wiring in Terraform

**Goal:** Connect S3 to SQS: (1) input bucket prefix `input/` suffix `.mp4` → chunking queue; (2) input bucket prefix `segments/` suffix `.mp4` → video-worker queue. No Lambda.

**Tasks:**

- In `packages/aws-infra`: S3 event notifications on input bucket for the two prefix/suffix combinations; grant S3 permission to send to the two queues.
- Document in `packages/aws-infra/README.md` the two flows.
- No code change in workers; they already consume raw S3 events.

**A/C:**

- [x] Upload to `input/{job_id}/source.mp4` causes message in chunking queue.
- [x] Upload to `segments/{job_id}/...mp4` causes message in video-worker queue.

**Verification:**

```bash
nx run aws-infra:terraform-plan
# After apply: upload test object to input/ and segments/ and check queue message counts.
```

---

### Step 4.3 — ECS compute (task definitions, services, ALB, scaling)

**Goal:** Terraform provisions ECS cluster, ECR (already exist), **task definitions** (env vars from Terraform: bucket names, table names, queue URLs, region), **IAM task roles** (one per workload, same permissions as prior IRSA). **Web-ui**: ECS Fargate service, 1 task, ALB in front. **Media-worker**: ECS Fargate service; scaling via Application Auto Scaling on a custom metric (e.g. sum of chunking + reassembly queue depths) or on one queue. **Video-worker**: ECS **EC2** launch type; capacity provider or ASG with GPU instance types (g4dn/g5), Spot + on-demand; scaling on video-worker queue depth. **Deploy flow:** Terraform apply → build/push images → force new deployment (or update task def with new image tag).

**Tasks:**

- In `packages/aws-infra`: ECS cluster; task definitions for web-ui, media-worker, video-worker (container defs with image from ECR + tag variable, env from Terraform outputs); IAM task roles (web-ui: S3 + DynamoDB Jobs; media-worker: S3 + DynamoDB + SQS chunking/reassembly; video-worker: S3 + DynamoDB SegmentCompletions + SQS video-worker); Fargate execution role for image pull and logs.
- **Web-ui:** Fargate service, desired 1, ALB + target group (HTTP 80 → 8000).
- **Media-worker:** Fargate service, desired 0 or 1; Application Auto Scaling on custom metric (chunking + reassembly queue depth sum) or single-queue metric.
- **Video-worker:** EC2 launch type, GPU in task definition; capacity provider or ASG with Spot + on-demand (g4dn/g5); scaling on video-worker queue depth.
- Document in `packages/aws-infra/README.md`: order of operations (terraform apply → build/push images → force new deployment), scaling and GPU capacity.
- **Nx deploy targets:** `deploy` on web-ui, media-worker, video-worker (source `packages/aws-infra/.env`, tag/push to ECR, `aws ecs update-service --force-new-deployment`). **stereocrafter-sagemaker:** `build` triggers CodeBuild (build image, push to ECR); `deploy` updates the SageMaker endpoint to use the new image (new model + endpoint config, then update-endpoint). `aws-infra:ecr-login` logs Docker into ECR using the same .env. Terraform output target writes to `packages/aws-infra/.env`.

**A/C:**

- [x] ECS cluster exists; three task definitions and three services (web-ui Fargate + ALB, media-worker Fargate with scaling, video-worker EC2 GPU with scaling).
- [x] Web-ui is reachable via ALB; workers scale on queue depth.
- [x] No EKS, Helm, or Argo CD in the main deployment path.

**Verification:**

```bash
nx run aws-infra:terraform-plan
# After apply: aws ecs list-services --cluster stereo-spot; curl ALB DNS
# Deploy: nx run aws-infra:ecr-login && nx run-many -t deploy
```

---

## Phase 5: Integration, docs, and hardening

### Step 5.1 — End-to-end and integration tests

**Goal:** Add integration tests in a **dedicated `packages/integration`** package that run the full pipeline against LocalStack or a test AWS account: create job → upload → chunking → video (stub) → SegmentCompletions → Lambda → reassembly → Job completed. Include **reassembly idempotency** test (duplicate messages, one winner).

**Tasks:**

- Create **`packages/integration`** with Nx project depending on web-ui, media-worker, video-worker (and optionally reassembly-trigger for Lambda-in-loop). Add target `test` (and optionally `smoke-test` if Step 2.3 lives here).
- Integration test suite: spin up LocalStack (or use test account); create job via API; put object to input; assert chunking queue message; run media-worker (processes chunking message); assert segment objects and video-worker messages; run video-worker (stub) for all segments; assert Lambda sent reassembly message; run media-worker (processes reassembly message); assert final.mp4 and Job completed.
- **Reassembly idempotency test:** For a job with all segments complete, send **two** reassembly messages (same job_id) and process both (e.g. run two media-worker instances or process messages twice). Assert: exactly one reassembly run produces final.mp4 and updates Job to completed; the other run skips (conditional update on ReassemblyTriggered fails) and deletes the message without overwriting. No duplicate or corrupted final file.
- Document in `docs/TESTING.md`: unit vs integration, how to run `nx run integration:test`, prerequisites (LocalStack/aws-cli). Note in plan/CI that `nx run integration:test` can be run when integration is enabled (env or flag).

**A/C:**

- [x] At least one automated flow covers job creation → completed.
- [x] Reassembly idempotency: two reassembly messages for same job_id result in exactly one reassembly run and one final.mp4.
- [x] docs/TESTING.md describes how to run all tests (including integration).

**Verification:**

```bash
nx run integration:test
```

---

### Step 5.2 — Operational runbooks and architecture cross-links

**Goal:** Add runbooks for common operations (chunking recovery—with script or exact procedure—DLQ handling, scaling limits) and ensure ARCHITECTURE.md and IMPLEMENTATION_PLAN are cross-referenced.

**Tasks:**

- **Chunking failure recovery:** Provide a **recovery script or CLI** (e.g. under `packages/tools` or `scripts/`) that: takes `job_id`; lists S3 prefix `segments/{job_id}/`; derives `total_segments` using the segment key parser from shared-types; performs a single DynamoDB UpdateItem to set `total_segments` and `status=chunking_complete` on the Job (with a safety check or confirmation). Alternatively, document in RUNBOOKS.md the **exact AWS CLI or boto3 steps** and the formula for total_segments (e.g. max segment_index + 1 or key parser) so the procedure is repeatable without a script.
- Add `docs/RUNBOOKS.md`: (1) Chunking failure recovery (reference script or step-by-step procedure above), (2) DLQ handling (inspect, replay or discard), (3) adjusting ECS service max capacity and SQS visibility timeout.
- In ARCHITECTURE.md add a short “Implementation” section linking to `docs/IMPLEMENTATION_PLAN.md`.
- In IMPLEMENTATION_PLAN.md ensure “Current state” and “Principles” reference ARCHITECTURE.md.

**A/C:**

- [x] Chunking failure recovery is repeatable via a script or a fully specified procedure in RUNBOOKS.md.
- [x] RUNBOOKS.md exists and covers chunking recovery, DLQ, and scaling.
- [x] ARCHITECTURE.md and IMPLEMENTATION_PLAN.md reference each other.

**Verification:**

- Read-through and link check.

---

### Step 5.3 — SageMaker-hosted StereoCrafter; video-worker as client

**Goal:** Host StereoCrafter on a **SageMaker real-time endpoint** (custom inference container). Model weights are **downloaded inside the SageMaker container at startup from Hugging Face**; the Hugging Face token (for gated models) is supplied via **AWS Secrets Manager** and injected into the container. The image stays small and weights are not on the developer machine. The **video-worker** becomes a thin client: it passes S3 input and **the canonical output URI** (`jobs/{job_id}/segments/{segment_index}.mp4`) to the endpoint; **SageMaker writes the stereo segment directly to that S3 key** (video-worker does not upload segment bytes). The video-worker only calls `InvokeEndpoint` and writes SegmentCompletion; it no longer needs a GPU and can run on **Fargate** (CPU only).

**Tasks:**

- **SageMaker inference container (new package or directory, e.g. `packages/stereocrafter-sagemaker`):**
  - Custom Docker image: base with CUDA 11.8, Python 3.8; clone StereoCrafter repo (or copy code); install dependencies and **Forward-Warp** (`dependency/Forward-Warp/install.sh`). Implement SageMaker contract: `GET /ping`, `POST /invocations`. **Request body:** JSON with `s3_input_uri` (segment in input bucket) and `s3_output_uri` (canonical output key `s3://output-bucket/jobs/{job_id}/segments/{segment_index}.mp4`). Handler reads the segment from S3, runs the two-stage pipeline (depth splatting → inpainting), and **writes the stereo output directly to the given `s3_output_uri`**; no response body needed beyond success/failure. This keeps the video-worker a thin client (no segment upload by the worker).
  - **Weights at startup:** In the container entrypoint or first request, download the three weight sets (SVD, DepthCrafter, StereoCrafter) from **Hugging Face** into a local directory; then load models. Read **HF token** from env (e.g. `HF_TOKEN`), which is populated from **Secrets Manager** by SageMaker so the container never sees the raw secret in the image. Document required env: `HF_TOKEN` (or the Secrets Manager secret ARN / key used to inject it). No weights baked into the image.
  - Build in CI (e.g. GitHub Actions or CodeBuild); push image to ECR.

- **Terraform (`packages/aws-infra`):**
  - **Secrets Manager:** Create a secret (e.g. `stereo-spot/hf-token`) for the Hugging Face token; document manual one-time value creation. SageMaker endpoint execution role needs `secretsmanager:GetSecretValue` on this secret.
  - SageMaker model resource (ECR image; optional `model_data_url` only if you use a small config artifact in S3).
  - SageMaker endpoint configuration (GPU instance, e.g. `ml.g4dn.xlarge` or `ml.g5.xlarge`). Inject the HF token into the container via SageMaker environment configuration: use the secret ARN so SageMaker resolves it at endpoint creation (e.g. env var `HF_TOKEN` from Secrets Manager).
  - SageMaker endpoint. IAM role for the endpoint: ECR pull, S3 read/write for invocation I/O, **Secrets Manager GetSecretValue** for the HF token secret.
  - Output endpoint name (and region) for video-worker config.
  - **Video-worker ECS:** Change from EC2 (GPU) to **Fargate** (CPU); add IAM permission `sagemaker:InvokeEndpoint` for the endpoint.

- **Video-worker (`packages/video-worker`):**
  - Add **`model_sagemaker.py`**: for SageMaker backend, **do not** download segment bytes or upload result. Instead: build the canonical output URI `s3://output-bucket/jobs/{job_id}/segments/{segment_index}.mp4` (from shared-types or env); call `sagemaker_runtime.invoke_endpoint` with JSON `{"s3_input_uri": "<segment_uri>", "s3_output_uri": "<canonical_output_uri>"}`. **SageMaker writes the stereo segment directly to that S3 URI.** Video-worker waits for a successful response, then the rest of the pipeline (unchanged) only writes the **SegmentCompletion** to DynamoDB (no upload step). Stub backend keeps the existing `process_segment(bytes) -> bytes` and upload in the runner for CI.
  - Env-driven backend: `INFERENCE_BACKEND=stub` (default for CI) vs `INFERENCE_BACKEND=sagemaker` with `SAGEMAKER_ENDPOINT_NAME` (and optionally `SAGEMAKER_REGION`). Wire in runner so no GPU is required when using SageMaker.
  - Unit tests: keep stub for CI; add tests for `model_sagemaker` with mocked `invoke_endpoint` (SageMaker path does not assert upload by video-worker).

- **Documentation:**
  - README for the SageMaker package: how the container works, weights download from Hugging Face at startup, env `HF_TOKEN` (injected from Secrets Manager), build and push. `packages/aws-infra/README.md`: order of operations (create Secrets Manager secret with HF token → terraform apply for SageMaker + ECS → build/push inference image → create/update endpoint → deploy video-worker with endpoint name). Document how to create/update the HF token secret. Video-worker README: `INFERENCE_BACKEND`, `SAGEMAKER_ENDPOINT_NAME`, segment size and timeout considerations. Optional: RUNBOOKS.md entry for "SageMaker endpoint update / weights refresh" and "HF token rotation."

**A/C:**

- [x] SageMaker custom container runs the inference contract; HF token is provided via Secrets Manager and injected into the container. (Container currently uses a stub that copies input→output; real StereoCrafter and HF weights at startup are Step 5.4.)
- [x] SageMaker handler writes the stereo segment **directly to the `s3_output_uri`** provided in the request (canonical key `jobs/{job_id}/segments/{segment_index}.mp4`); video-worker does not upload segment bytes.
- [x] Video-worker invokes the endpoint when `INFERENCE_BACKEND=sagemaker`; stub remains for CI; video-worker runs on Fargate (no GPU).
- [x] Documentation covers endpoint deploy order, env vars, and segment sizing/timeouts.

**Verification:**

```bash
nx run video-worker:test
# Manual: deploy endpoint, set INFERENCE_BACKEND=sagemaker and SAGEMAKER_ENDPOINT_NAME, run one segment through pipeline.
```

---

### Step 5.4 — Real StereoCrafter inference in SageMaker container

**Goal:** Replace the stub in `packages/stereocrafter-sagemaker` with the real two-stage pipeline (depth splatting → inpainting). Weights are downloaded from Hugging Face at container startup using the injected HF token; no weights baked into the image.

**Tasks:**

- In **`packages/stereocrafter-sagemaker`**: base image with CUDA and Python; add StereoCrafter code and dependencies (e.g. Forward-Warp). In the container entrypoint or first request: download the three weight sets (SVD, DepthCrafter, StereoCrafter) from Hugging Face using `HF_TOKEN`; load models. In `POST /invocations`: read segment from `s3_input_uri`, run the two-stage pipeline, write stereo output to `s3_output_uri`. Keep `GET /ping` and the existing request/response contract.
- Document in the package README: weight download at startup, required env, and any segment size/timeout limits for real inference.

**A/C:**

- [x] Container downloads StereoCrafter (and dependency) weights from Hugging Face at startup using the Secrets Manager–injected HF token.
- [x] Handler runs the full two-stage pipeline and writes the stereo segment to `s3_output_uri`; endpoint is usable for production segments.

**Verification:**

- Deploy updated image to SageMaker; run a segment through the pipeline and confirm stereo output in S3.

---

## Summary table

| Step | Package / Area             | Main deliverable                                                                      | Tests / Docs                |
| ---- | -------------------------- | ------------------------------------------------------------------------------------- | --------------------------- |
| 1.1  | shared-types               | Python package skeleton, Nx, pytest                                                   | 1 test; README              |
| 1.2  | shared-types               | Pydantic models, segment + input key parser                                           | Unit tests; README          |
| 1.3  | shared-types               | Cloud abstraction interfaces                                                          | Mock tests; SHARED_TYPES.md |
| 2.1  | aws-infra                  | S3, SQS, DynamoDB, DLQ alarms (no EKS)                                                | README                      |
| 2.2  | aws-adapters               | AWS implementations of interfaces                                                     | Moto tests; README          |
| 2.3  | integration / aws-adapters | Data plane smoke test                                                                 | TESTING.md or README        |
| 3.1  | media-worker               | Chunking + reassembly (one image, two queues) + Docker                                | Unit tests; README          |
| 3.2  | video-worker               | Stub model + pipeline                                                                 | Unit tests; README          |
| 3.4  | reassembly-trigger         | Lambda Streams → SQS (shared-types from wheel)                                        | Unit tests; README          |
| 4.1  | web-ui                     | FastAPI + Jinja2 routes                                                               | Unit tests; README          |
| 4.2  | aws-infra                  | S3 → SQS event notifications                                                          | README                      |
| 4.3  | aws-infra                  | ECS cluster, task definitions, services (Fargate + EC2 GPU), ALB, task roles, scaling | README                      |
| 5.1  | integration                | E2E test + reassembly idempotency                                                     | TESTING.md                  |
| 5.2  | docs / tools               | Runbooks, chunking recovery script/procedure, cross-links                             | RUNBOOKS.md                 |
| 5.3  | stereocrafter-sagemaker, aws-infra, video-worker | SageMaker endpoint (custom container; stub handler; Secrets Manager for HF token), video-worker InvokeEndpoint, Fargate | README; video-worker tests (stub + mocked SageMaker) |
| 5.4  | stereocrafter-sagemaker                          | Real StereoCrafter inference in container; HF weights at startup                                                         | README                                                |

---

## Dependency graph (Nx)

After implementation, expected dependency structure:

- **shared-types** — no package deps.
- **aws-adapters** — depends on **shared-types**.
- **media-worker**, **video-worker**, **web-ui** — depend on **shared-types** and **aws-adapters** (for AWS implementations at runtime).
- **reassembly-trigger** — depends on **shared-types** (build: install from shared-types wheel).
- **integration** — depends on **web-ui**, **media-worker**, **video-worker** (and optionally **reassembly-trigger** for Lambda-in-loop tests). May also host the Step 2.3 smoke test (e.g. `integration:smoke-test`).
- **aws-infra** — depends on **aws-infra-setup** (already). Provisions ECS cluster, task definitions, services, ALB, **CodeBuild** (stereocrafter-sagemaker), SageMaker model, endpoint config, endpoint. Video-worker task role has `sagemaker:InvokeEndpoint`.
- **stereocrafter-sagemaker** — `build` triggers **CodeBuild** to clone the repo, build the inference Docker image, and push to ECR (no local Docker build). `deploy` updates the SageMaker endpoint to use the new ECR image (create model + endpoint config, update-endpoint). SageMaker model references the ECR image. Weights are downloaded inside the container at startup, not in the image.
- **video-worker** — when using SageMaker (Step 5.3), runs on Fargate (CPU) and calls the SageMaker endpoint; no GPU required.

Use `nx run-many -t test` to run tests for all projects; use `nx run-many -t build` for buildable packages. Ensure CI runs tests and, when enabled, `nx run integration:test` on every PR.
