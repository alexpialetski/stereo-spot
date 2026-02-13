# Stereo-Spot Implementation Plan

This document provides an **incremental implementation plan** for the stereo-spot application as described in [ARCHITECTURE.md](../ARCHITECTURE.md). Each step is designed to be shippable, with unit tests and documentation. All steps include **Acceptance Criteria (A/C)** and **Verification** instructions.

**Current state:** Phase 1 and Step 2.1–2.3 are done. **packages/shared-types** exists (Pydantic models, segment/input key parsers, cloud abstraction interfaces). **packages/aws-infra-setup** provisions the Terraform S3 backend. **packages/aws-infra** provisions the data plane: two S3 buckets (input, output), three SQS queues + DLQs, three DynamoDB tables (Jobs with GSI, SegmentCompletions, ReassemblyTriggered with TTL), and CloudWatch alarms for each DLQ. **packages/aws-adapters** implements AWS backends for JobStore, SegmentCompletionStore, QueueSender/Receiver, ObjectStorage (exists, upload_file), and ReassemblyTriggeredLock (moto tests, env-based config). Data plane smoke test runs via `nx run aws-adapters:smoke-test` using `terraform-outputs.env`. **Step 3.1** is done: **packages/chunking-worker** consumes the chunking queue (S3 event), parses input key via shared-types, fetches job and mode, runs ffmpeg chunking, uploads segments with canonical keys, updates Job to chunking_complete (unit tests, README, Dockerfile). **Step 3.2** is done: **packages/video-worker** consumes the video-worker queue (S3 event), parses segment key via shared-types, runs stub model (copy), uploads to output bucket, writes SegmentCompletion (unit tests, README). **Step 3.3** is done: **packages/reassembly-worker** consumes the reassembly queue (job_id), acquires lock via ReassemblyTriggered (conditional update), queries SegmentCompletions, builds concat list, runs ffmpeg concat, uploads final.mp4 (multipart for large files), updates Job to completed (unit tests, README, Dockerfile). **Step 3.4** is done: **packages/reassembly-trigger** Lambda (DynamoDB Streams on SegmentCompletions), conditional create on ReassemblyTriggered, send job_id to reassembly queue; build from shared-types wheel (Nx build + script), Terraform (Lambda, stream event source, IAM, env), unit tests, README. S3 event notifications (Step 4.2), web-ui, and Helm are not yet implemented.

**Principles:**

- Implement in dependency order: shared-types → workers & Lambda → web-ui → Helm → full AWS (EKS, etc.).
- Add unit tests and markdown docs in the same step as the feature.
- Verify with Nx tasks and automated tests where possible.

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

**Goal:** Implement the single source of truth for Job, Segment, SegmentCompletion, queue payloads, and API DTOs. Implement the **segment key format and parser** only in this package (used later by chunking-worker and video-worker).

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
- Add `docs/SHARED_TYPES.md` (or section in package README) describing each interface and intended usage (e.g. “JobStore is used by web-ui and chunking-worker”).
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
- Document in `packages/aws-adapters/README.md` how to wire implementations (e.g. `STORAGE_ADAPTER=aws` and required env vars). List which packages consume aws-adapters (web-ui, chunking-worker, video-worker, reassembly-worker).

**A/C:**

- [x] All four abstraction interfaces have AWS implementations in `packages/aws-adapters`.
- [x] Unit tests run against moto (or equivalent) and pass.
- [x] Documentation explains configuration and env vars.

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

### Step 3.1 — Chunking worker package

**Goal:** New package `packages/chunking-worker`: consumes chunking queue (raw S3 event), parses job_id from key, fetches mode from JobStore, downloads source, runs ffmpeg chunking, uploads segments with canonical key, updates Job to chunking_complete with total_segments.

**Tasks:**

- Create `packages/chunking-worker` with pyproject.toml (depends on shared-types), Nx project.json (build, test, lint), and Dockerfile.
- Implement: read S3 event from queue; parse input key via shared-types; get job from JobStore; update job to chunking*in_progress; download source to temp; ffmpeg segment (keyframe-aligned, ~50MB/~5min); upload each segment with `segments/{job_id}/{i:05d}*{total:05d}\_{mode}.mp4`; single UpdateItem for total_segments + status=chunking_complete.
- Use abstractions (JobStore, ObjectStorage, QueueReceiver); inject AWS implementations via env/config.
- Unit tests: (1) parsing S3 event and input key, (2) segment key generation for a given job_id/mode/total, (3) mock JobStore/ObjectStorage and run one chunking flow (small fixture file or no real ffmpeg).
- Add `packages/chunking-worker/README.md`: purpose, env vars, local run, Docker build.

**A/C:**

- [x] Worker uses only shared-types for key parsing and key building.
- [x] Unit tests pass; at least one test with mocked stores and optional small-file ffmpeg.
- [x] README documents behaviour and how to run.

**Verification:**

```bash
nx run chunking-worker:test
nx run chunking-worker:build   # if Docker build is the “build” target
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

### Step 3.3 — Reassembly worker package

**Goal:** New package `packages/reassembly-worker`: consumes reassembly queue (job_id), acquires lock via ReassemblyTriggered (conditional update), queries SegmentCompletions by job_id, builds concat list, runs ffmpeg concat, uploads final.mp4, updates Job to completed.

**Tasks:**

- Create package; depend on shared-types (and abstractions). Implement: receive job_id; conditional update on ReassemblyTriggered (reassembly_started_at); if failed, skip and delete message; query SegmentCompletions by job_id; build concat list (use deterministic path or output_s3_uri); download segments (or use S3 URI list); ffmpeg concat; upload to `jobs/{job_id}/final.mp4` (multipart for large files); update Job status=completed, completed_at; delete message.
- Unit tests: (1) concat list building from SegmentCompletions, (2) conditional write behaviour (mock), (3) idempotency when final.mp4 exists.
- README: flow, env vars, lock semantics.

**A/C:**

- [x] Worker uses ReassemblyTriggered for single-run guarantee; uses SegmentCompletions only (no S3 list) for segment list.
- [x] Unit tests pass.

**Verification:**

```bash
nx run reassembly-worker:test
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
- Add `packages/web-ui/README.md`: routes, env vars, IRSA note for EKS.

**A/C:**

- [ ] All routes from ARCHITECTURE implemented (dashboard, list, create, detail, play).
- [ ] Presigned URLs use keys: `input/{job_id}/source.mp4` and `jobs/{job_id}/final.mp4`.
- [ ] Unit tests pass.

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

- [ ] Upload to `input/{job_id}/source.mp4` causes message in chunking queue.
- [ ] Upload to `segments/{job_id}/...mp4` causes message in video-worker queue.

**Verification:**

```bash
nx run aws-infra:terraform-plan
# After apply: upload test object to input/ and segments/ and check queue message counts.
```

---

### Step 4.3 — Helm chart and Argo CD Application

**Goal:** One umbrella Helm chart in `packages/helm`: Deployments/Services for web-ui, chunking-worker, video-worker, reassembly-worker; Ingress for web-ui; KEDA ScaledObjects for the three worker queues; image pull from ECR. Argo CD Application manifest pointing at this repo path. Helm values must receive queue URLs, bucket names, and table names from Terraform.

**Tasks:**

- Create `packages/helm` with Chart.yaml, values.yaml (placeholders or defaults for image tags, queue URLs, bucket names, table names). **Define how Terraform outputs feed Helm:** Terraform will generate a values file (e.g. `packages/helm/values-from-terraform.yaml`) after apply—e.g. via a `local_file` or null_resource that writes queue URLs, bucket names, table names, ECR repo URIs from Terraform outputs. Argo CD (or the Application) uses this file so the chart receives resource names without manual copy. Document this in `packages/helm/README.md`.
- Templates: Deployment and Service per app; Ingress (e.g. ALB or Ingress controller); KEDA ScaledObject for chunking, video-worker, reassembly queues.
- Argo CD Application YAML (e.g. `argo-application.yaml` or `applications/stereo-spot.yaml`) in same package; Terraform will apply it after installing Argo CD.
- Document in `packages/helm/README.md`: structure, how to set image tags, how Terraform-generated values are used, how Argo CD syncs.

**A/C:**

- [ ] `helm template` produces valid manifests for all four workloads and KEDA.
- [ ] Terraform (or a documented CI step) produces a values file with queue URLs, bucket names, table names; Argo CD / Helm use it.
- [ ] Argo CD Application manifest references this repo and path.
- [ ] README explains chart, Terraform→values flow, and deployment flow.

**Verification:**

```bash
helm dependency update packages/helm  # if any
helm template stereo-spot packages/helm -f packages/helm/values.yaml
```

---

### Step 4.4 — EKS, ECR, Argo CD, Karpenter, and full infra in Terraform

**Goal:** Terraform provisions EKS cluster, ECR repos (web-ui, chunking-worker, video-worker, reassembly-worker), IRSA for each, installs Argo CD controller and applies Argo CD Application from packages/helm. **Karpenter** and at least one GPU node pool are included so video-worker pods can schedule. **Node Termination Handler** is required for graceful Spot reclaim (segment-level retry).

**Tasks:**

- In `packages/aws-infra`: EKS cluster (with OIDC for IRSA); ECR repositories; IAM roles and IRSA for web-ui and each worker.
- **Node Termination Handler:** Install the AWS Node Termination Handler (e.g. Helm chart or manifest) so nodes receive SIGTERM before Spot reclaim. Required for architecture’s error-handling goals.
- **Karpenter:** Install Karpenter (Helm or manifest) and create at least one NodePool (or NodeClass) for GPU nodes (e.g. g4dn or g5), with Spot capacity type and a small on-demand fallback. Set max nodes (e.g. 4–8) as a variable. Without this, video-worker pods will remain Pending.
- Helm release for Argo CD; kubectl/kubernetes provider to apply Argo CD Application manifest(s) from helm package. Ensure Helm/Argo CD receive queue URLs, bucket names, and table names from Terraform (see Step 4.3).
- Document in `packages/aws-infra/README.md`: order of operations (terraform apply → build/push images → update tag in values → Argo CD sync), scaling/GPU section (where NodePool is defined, how to change max GPU nodes), and any manual steps.

**A/C:**

- [ ] Terraform apply creates EKS, ECR repos, IRSA; Argo CD is installed and Application points at repo.
- [ ] Node Termination Handler is running in the cluster (e.g. DaemonSet or Helm release present).
- [ ] Karpenter and at least one GPU node pool exist; video-worker pods can schedule after 4.4.
- [ ] Helm/Argo CD receive queue URLs, bucket names, and table names from Terraform (documented mechanism).
- [ ] After image push and tag update, Argo CD can sync and deploy workloads.

**Verification:**

```bash
nx run aws-infra:terraform-plan
# After apply: kubectl get nodes; kubectl get applications -n argocd
```

---

## Phase 5: Integration, docs, and hardening

### Step 5.1 — End-to-end and integration tests

**Goal:** Add integration tests in a **dedicated `packages/integration`** package that run the full pipeline against LocalStack or a test AWS account: create job → upload → chunking → video (stub) → SegmentCompletions → Lambda → reassembly → Job completed. Include **reassembly idempotency** test (duplicate messages, one winner).

**Tasks:**

- Create **`packages/integration`** with Nx project depending on web-ui, chunking-worker, video-worker, reassembly-worker (and optionally reassembly-trigger for Lambda-in-loop). Add target `test` (and optionally `smoke-test` if Step 2.3 lives here).
- Integration test suite: spin up LocalStack (or use test account); create job via API; put object to input; assert chunking queue message; run chunking worker once; assert segment objects and video-worker messages; run video-worker (stub) for all segments; assert Lambda sent reassembly message; run reassembly worker; assert final.mp4 and Job completed.
- **Reassembly idempotency test:** For a job with all segments complete, send **two** reassembly messages (same job_id) and process both (e.g. run two reassembly workers or process messages twice). Assert: exactly one reassembly run produces final.mp4 and updates Job to completed; the other run skips (conditional update on ReassemblyTriggered fails) and deletes the message without overwriting. No duplicate or corrupted final file.
- Document in `docs/TESTING.md`: unit vs integration, how to run `nx run integration:test`, prerequisites (LocalStack/aws-cli). Note in plan/CI that `nx run integration:test` can be run when integration is enabled (env or flag).

**A/C:**

- [ ] At least one automated flow covers job creation → completed.
- [ ] Reassembly idempotency: two reassembly messages for same job_id result in exactly one reassembly run and one final.mp4.
- [ ] docs/TESTING.md describes how to run all tests (including integration).

**Verification:**

```bash
nx run integration:test
```

---

### Step 5.2 — Operational runbooks and architecture cross-links

**Goal:** Add runbooks for common operations (chunking recovery—with script or exact procedure—DLQ handling, scaling limits) and ensure ARCHITECTURE.md and IMPLEMENTATION_PLAN are cross-referenced.

**Tasks:**

- **Chunking failure recovery:** Provide a **recovery script or CLI** (e.g. under `packages/tools` or `scripts/`) that: takes `job_id`; lists S3 prefix `segments/{job_id}/`; derives `total_segments` using the segment key parser from shared-types; performs a single DynamoDB UpdateItem to set `total_segments` and `status=chunking_complete` on the Job (with a safety check or confirmation). Alternatively, document in RUNBOOKS.md the **exact AWS CLI or boto3 steps** and the formula for total_segments (e.g. max segment_index + 1 or key parser) so the procedure is repeatable without a script.
- Add `docs/RUNBOOKS.md`: (1) Chunking failure recovery (reference script or step-by-step procedure above), (2) DLQ handling (inspect, replay or discard), (3) adjusting Karpenter/max nodes and SQS visibility timeout.
- In ARCHITECTURE.md add a short “Implementation” section linking to `docs/IMPLEMENTATION_PLAN.md`.
- In IMPLEMENTATION_PLAN.md ensure “Current state” and “Principles” reference ARCHITECTURE.md.

**A/C:**

- [ ] Chunking failure recovery is repeatable via a script or a fully specified procedure in RUNBOOKS.md.
- [ ] RUNBOOKS.md exists and covers chunking recovery, DLQ, and scaling.
- [ ] ARCHITECTURE.md and IMPLEMENTATION_PLAN.md reference each other.

**Verification:**

- Read-through and link check.

---

### Step 5.3 — Replace video-worker stub with StereoCrafter (or real model)

**Goal:** Swap the stub model in video-worker for the real StereoCrafter (or chosen model) pipeline; document GPU requirements and segment sizing; ensure Docker image has CUDA and model weights (or pull at runtime).

**Tasks:**

- Implement model loading and inference in video-worker; keep interface swappable (e.g. plugin or env-driven class).
- Dockerfile: base image with CUDA, Python, PyTorch; copy or download model weights (Secrets Manager or S3).
- Update README: GPU sizing, segment length vs wall-clock, Karpenter node class (e.g. g4dn).
- Unit test: keep stub path for CI; optional integration test with small segment on GPU.

**A/C:**

- [ ] Video worker runs StereoCrafter (or target model) when configured.
- [ ] Documentation covers GPU and segment sizing.

**Verification:**

```bash
nx run video-worker:test
# Manual: run one segment through real model in dev.
```

---

## Summary table

| Step | Package / Area             | Main deliverable                                             | Tests / Docs                |
| ---- | -------------------------- | ------------------------------------------------------------ | --------------------------- |
| 1.1  | shared-types               | Python package skeleton, Nx, pytest                          | 1 test; README              |
| 1.2  | shared-types               | Pydantic models, segment + input key parser                  | Unit tests; README          |
| 1.3  | shared-types               | Cloud abstraction interfaces                                 | Mock tests; SHARED_TYPES.md |
| 2.1  | aws-infra                  | S3, SQS, DynamoDB, DLQ alarms (no EKS)                       | README                      |
| 2.2  | aws-adapters               | AWS implementations of interfaces                            | Moto tests; README          |
| 2.3  | integration / aws-adapters | Data plane smoke test                                        | TESTING.md or README        |
| 3.1  | chunking-worker            | Chunking logic + Docker                                      | Unit tests; README          |
| 3.2  | video-worker               | Stub model + pipeline                                        | Unit tests; README          |
| 3.3  | reassembly-worker          | Concat + lock + Job update                                   | Unit tests; README          |
| 3.4  | reassembly-trigger         | Lambda Streams → SQS (shared-types from wheel)               | Unit tests; README          |
| 4.1  | web-ui                     | FastAPI + Jinja2 routes                                      | Unit tests; README          |
| 4.2  | aws-infra                  | S3 → SQS event notifications                                 | README                      |
| 4.3  | helm                       | Chart + Argo CD Application, Terraform→values                | README; helm template       |
| 4.4  | aws-infra                  | EKS, ECR, Argo CD, IRSA, Karpenter, Node Termination Handler | README                      |
| 5.1  | integration                | E2E test + reassembly idempotency                            | TESTING.md                  |
| 5.2  | docs / tools               | Runbooks, chunking recovery script/procedure, cross-links    | RUNBOOKS.md                 |
| 5.3  | video-worker               | Real StereoCrafter model                                     | README; optional GPU test   |

---

## Dependency graph (Nx)

After implementation, expected dependency structure:

- **shared-types** — no package deps.
- **aws-adapters** — depends on **shared-types**.
- **chunking-worker**, **video-worker**, **reassembly-worker**, **web-ui** — depend on **shared-types** and **aws-adapters** (for AWS implementations at runtime).
- **reassembly-trigger** — depends on **shared-types** (build: install from shared-types wheel).
- **integration** — depends on **web-ui**, **chunking-worker**, **video-worker**, **reassembly-worker** (and optionally **reassembly-trigger** for Lambda-in-loop tests). May also host the Step 2.3 smoke test (e.g. `integration:smoke-test`).
- **helm** — no Nx dependency on other app packages (references images and config).
- **aws-infra** — depends on **aws-infra-setup** (already).

Use `nx run-many -t test` to run tests for all projects; use `nx run-many -t build` for buildable packages. Ensure CI runs tests and, when enabled, `nx run integration:test` on every PR.
