This architecture is designed for

**high-throughput, cost-optimized video processing** using a "Job-Worker" pattern.

> **Implementation:** For an incremental build plan with steps, acceptance criteria, and verification, see [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

### Implementation

- **Build plan:** [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) — incremental steps, acceptance criteria, and verification for each phase.
- **Runbooks:** [docs/RUNBOOKS.md](docs/RUNBOOKS.md) — chunking failure recovery, DLQ handling, and ECS/SQS scaling.

It leverages **ECS (Elastic Container Service)** with **Fargate** for all app workloads (web-ui, media-worker, video-worker) and **SageMaker** for GPU inference (StereoCrafter); **NX** provides shared logic between your UI and Infrastructure-as-Code (IaC).

🏗️ NX Monorepo Structure

Using NX, you unify your frontend, cloud infrastructure, and worker logic. All projects live under **`packages/`** (no `apps/` or `libs/` folders).

- `packages/web-ui`: **FastAPI** app (Python) **deployed on ECS Fargate**; **server-rendered UI** (Jinja2 templates). Serves HTML pages for the dashboard, job list, and playback; form POST for job creation (redirect to page with upload URL). Talks to AWS (S3, DynamoDB) via **IAM task role** for presigned URLs, uploads, and listing. See Web UI below.
- `packages/media-worker`: **Single package and Docker image** for all CPU/ffmpeg work: **chunking** (split source with ffmpeg, upload segments to S3) and **reassembly** (ffmpeg concat to produce final 3D file). Consumes both the chunking and reassembly SQS queues in one process (two threads). Runs on **ECS Fargate**; scaled by **Application Auto Scaling** on SQS queue depth (chunking + reassembly). Saves storage (~600MB one image instead of two). See Chunking and Reassembly below.
- `packages/video-worker`: **Thin client** (Python container). Pulls messages from the video-worker queue, passes segment S3 URI and canonical output S3 URI to a **SageMaker** real-time endpoint; the endpoint runs **StereoCrafter** (or swappable model) and writes the stereo segment directly to that output key. The video-worker then writes the SegmentCompletion record. Runs on **ECS Fargate** (no GPU). See The Video Worker below.
- `packages/stereocrafter-sagemaker` (or equivalent): Custom **SageMaker inference container** (CUDA, StereoCrafter two-stage pipeline). Model weights are downloaded from Hugging Face at endpoint startup; **Secrets Manager** holds the HF token. The handler receives `s3_input_uri` and `s3_output_uri`, runs inference, and writes the result to the given S3 key. Deployed as a SageMaker model and endpoint via Terraform; image pushed to ECR.
- `packages/shared-types`: **Python library** (no Docker image). Single source of truth for job, segment, and message shapes used across the pipeline. Defines **Pydantic** models for Jobs, queue payloads, DynamoDB record shapes, and API DTOs. Consumed by `web-ui`, `media-worker`, `video-worker`, and by Lambda (e.g. reassembly trigger, S3 enrichment) when implemented in Python. See Shared types and library below.
- `packages/aws-infra-setup`: Terraform backend project that provisions the state file (S3 bucket, DynamoDB for locking). Uses the **nx-terraform** plugin (automatic project discovery and inferred tasks for init, plan, apply, destroy, validate, fmt, output). Linked to `aws-infra`. See [nx-terraform](https://alexpialetski.github.io/nx-terraform/) for documentation.
- `packages/aws-infra`: Terraform project containing the actual AWS infrastructure: S3, SQS, DynamoDB, Lambda, **ECS cluster**, **ECR**, **task definitions and services** (Fargate for web-ui, media-worker, and video-worker), **SageMaker** (model, endpoint config, endpoint for StereoCrafter), **ALB**, **Secrets Manager** (e.g. HF token for SageMaker). Uses **nx-terraform** with a backend dependency on `aws-infra-setup`; Nx ensures correct execution order and dependency graph.
- `packages/reassembly-trigger`: **Python Lambda** (no separate Nx app folder required if small; can live under `packages/reassembly-trigger`). Consumes DynamoDB Streams from SegmentCompletions and sends `job_id` to the Reassembly SQS queue when the last segment is done. Depends on `shared-types`; CI bundles shared-types into the Lambda deployment package (e.g. `pip install -t . ../shared-types` then zip). Deployed via Terraform.

To add Google Cloud later, add separate packages: `packages/google-infra-setup` (state) and `packages/google-infra` (GCP resources), following the same nx-terraform pattern.

**Portability and cloud abstractions:** To avoid vendor lock-in and simplify a future GCP (or other cloud) deployment, use **abstractions from the beginning**. Pipeline logic uses **shared-types** and thin interfaces (e.g. in `packages/shared-types`) for: **job store** (get/put/update job), **segment-completion store** (put completion, query by job ordered by segment_index), **queues** (send/receive messages), and **object storage** (presign upload/download, upload/download). **AWS** implementations live in **packages/aws-adapters** (DynamoDB, SQS, S3). **Compute** is cloud-specific: on AWS we use ECS Fargate for all workloads and **SageMaker** for GPU inference; on GCP you would use Cloud Run and/or GKE with the same container images, plus a GCP equivalent for the inference endpoint (e.g. Vertex AI), and env-based config. Add **GCP** implementations later (e.g. Firestore, Pub/Sub, GCS) behind the same interfaces. App and workers depend on the abstractions and get the implementation by config (e.g. `STORAGE_ADAPTER=aws`). Terraform remains per-cloud; application and worker code stay the same.

---

📐 Shared types and library (packages/shared-types)

With an all-Python app layer (FastAPI, Python workers, Python Lambda), a **single Python package** provides shared domain and message types so every component uses the same shapes and stays in sync. Terraform does not consume these types; it only outputs resource names/ARNs (queue URLs, bucket names, etc.).

**Recommended approach:**

- **Format:** A **Python library** under `packages/shared-types` using **Pydantic** models. No Protobuf or JSON schema is required for the current stack; Pydantic gives validation, serialization, and a single source of truth. If you add non-Python consumers later, you can introduce a schema format (e.g. JSON Schema export from Pydantic) or Protobuf in addition.
- **Segment key convention (single source of truth):** Segment object keys in the input bucket follow **one** format so media-worker and video-worker stay in sync: `segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4` (zero-padding keeps lexicographic order and avoids ambiguity). The **parser lives only in `shared-types`** (e.g. function or Pydantic validator that takes `bucket + key` and returns the canonical segment payload). Both media-worker (when building keys) and video-worker (when parsing S3 events) use this; no duplicate parsing logic elsewhere.
- **Contents:** The library defines models for:
  - **Job:** `job_id`, `mode` (e.g. literal `anaglyph` | `sbs`), `status` (e.g. `created`, `chunking_complete`, `completed`), optional `created_at`, `total_segments`, `completed_at` — used by web-ui (DynamoDB, API), chunking message, reassembly trigger, and job metadata lookups. "List available movies" queries Jobs with `status = completed`.
  - **Chunking message:** The chunking queue receives the **raw S3 event** (bucket, key). The media-worker parses `job_id` from the key and fetches `mode` from DynamoDB to form the logical payload: `input_s3_uri`, `job_id`, `mode` (consumed by media-worker).
  - **Segment / video-worker message:** `job_id`, `segment_index`, `total_segments`, `segment_s3_uri`, `mode` — payload for the video-worker queue. With **S3→SQS direct**, the queue receives the raw S3 event (bucket, key); the video-worker uses the **segment key parser from `shared-types`** to produce this canonical payload — no Lambda required.
  - **SegmentCompletion:** `job_id`, `segment_index`, `output_s3_uri`, `completed_at`, optional `total_segments` — DynamoDB SegmentCompletions record (written by video-worker; read by reassembly Lambda and media-worker).
  - **Reassembly message:** `job_id` — payload for the Reassembly SQS queue (sent by Lambda, consumed by media-worker).
  - **API DTOs:** e.g. `CreateJobRequest` (mode), `CreateJobResponse` (job_id, upload_url), `JobListItem`, `PresignedPlaybackResponse` — used by FastAPI for request/response validation and OpenAPI.
- **Consumers:** `web-ui`, `media-worker`, and `video-worker` declare a dependency on `packages/shared-types` in the Nx graph (and in their Python dependency file, e.g. pyproject.toml). **Lambda functions** (e.g. reassembly trigger) are Python and use the same types: the **simplest approach** is to **bundle** `shared-types` into the Lambda deployment package in CI (e.g. `pip install -t . ../shared-types` then zip), so no separate layer is required.
- **Build and versioning:** The shared-types package is a normal Nx project (e.g. build target that produces a wheel or installable package). Workers and web-ui depend on it so Nx runs the shared-types build first when building or testing dependents. All apps and workers use the same version from the monorepo; no separate versioning unless you later publish it.

**Summary:** One Python library, Pydantic models, consumed by FastAPI and all Python workers (and Lambda). Keeps job, segment, completion, and API contracts in one place and avoids drift across the pipeline.

---

🖥️ Web UI (packages/web-ui)

**FastAPI** is **deployed on ECS Fargate**. The UI is **server-rendered** (Jinja2): **GET requests for pages return HTML** (dashboard, job list, job detail). Job creation is **form POST** (e.g. select mode, submit) → server creates the job and **redirects** to a page that shows the upload URL and instructions. List of available movies and playback are **HTML pages** (list rendered from DynamoDB; playback can be a link or redirect to the presigned S3 URL). The app talks to **AWS services** (S3, DynamoDB) using **IAM task role**—no long-lived credentials; the browser never sees AWS credentials. Optional: a small **JSON API** under `/api/` (e.g. for future "copy playback link" or automation); for V1, HTML and redirects are sufficient.

- **Job creation and upload:** The user selects **mode** (anaglyph | sbs) in the UI. The FastAPI API **creates a job** (e.g. writes to a DynamoDB Jobs table: `job_id`, `mode`, `status: created`) and returns `job_id` plus a **presigned upload URL** for a deterministic key, e.g. `input/{job_id}/source.mp4`. The browser uploads directly to that URL. When the upload completes, an **S3 event notification** is sent **directly to the chunking SQS queue** (no Lambda). The message payload is the S3 event (bucket, key). The **chunking worker** parses `job_id` from the key (`input/{job_id}/source.mp4`), fetches `mode` from the DynamoDB Jobs table, and proceeds with chunking (see Orchestration).
- **List available movies:** The UI displays **available (completed) movies**. The FastAPI API **queries DynamoDB** using the **GSI** on `(status, completed_at)`: query with `status = 'completed'`, descending by `completed_at`, with pagination (`Limit`, `ExclusiveStartKey`). Returns job_id, mode, completed_at, etc.; the UI shows titles, job id, mode (anaglyph/SBS), and status. Presigned playback URLs are generated from the known path `jobs/{job_id}/final.mp4`. Do not rely on S3 list for "available" — DynamoDB is authoritative.
- **Presigned URL for local playback:** For each available movie, the user can request a **presigned GET URL**. With server-rendered UI this is typically a **GET page** that responds with HTML containing the link, or a **redirect** to the presigned S3 URL; the user opens it in a local player (e.g. VLC, mpv) or the browser. The bucket stays private.

**Pages and routes (server-rendered):** GET `/` → dashboard (HTML); GET `/jobs` (or equivalent) → list of completed jobs (HTML from DynamoDB); POST `/jobs` (form: mode) → create job, redirect to page with upload URL; GET `/jobs/{job_id}` → job detail/status (HTML); GET `/jobs/{job_id}/play` → redirect to presigned URL or HTML with link. OpenAPI/JSON at `/openapi.json` if needed for docs or future API consumers.

**Job creation flow:**

```mermaid
sequenceDiagram
    participant User
    participant UI as FastAPI
    participant DDB as DynamoDB (Jobs)
    participant S3
    participant ChunkQ as Chunking Queue

    User->>UI: Select mode, request upload URL
    UI->>DDB: Create job (job_id, mode, status: created)
    DDB-->>UI: ok
    UI-->>User: job_id + presigned URL (input/{job_id}/source.mp4)
    User->>S3: PUT source.mp4 (presigned)
    S3->>ChunkQ: S3 event notification → chunking queue (bucket, key)
```

---

☁️ Infrastructure Architecture (AWS Implementation)

**High-level infrastructure:**

```mermaid
flowchart TB
    subgraph External
        User[User / Browser]
    end

    subgraph AWS["AWS Account"]
        subgraph VPC["VPC"]
            ALB[ALB]
            subgraph ECS["ECS Cluster"]
                WebUI[web-ui Fargate]
                MediaW[media-worker Fargate]
                VideoW[video-worker Fargate]
            end
        end

        SageMaker[SageMaker\nStereoCrafter endpoint]
        ECR[(ECR)]

        subgraph Storage["S3"]
            InputBucket[(input bucket)]
            OutputBucket[(output bucket)]
        end

        subgraph Queues["SQS"]
            ChunkQ[chunking queue]
            VideoQ[video-worker queue]
            ReassQ[reassembly queue]
        end

        subgraph DB["DynamoDB"]
            Jobs[(Jobs)]
            SegCompl[(SegmentCompletions)]
            ReassTrig[(ReassemblyTriggered)]
        end

        Lambda[Lambda\nreassembly trigger]
    end

    User -->|HTTPS| ALB
    ALB --> WebUI
    User -->|presigned PUT| InputBucket
    WebUI -->|task role| InputBucket
    WebUI -->|task role| OutputBucket
    WebUI -->|task role| Jobs
    InputBucket -->|S3 event notification| ChunkQ
    MediaW -->|pull| ChunkQ
    MediaW -->|upload segments| InputBucket
    InputBucket -->|S3 event| VideoQ
    VideoW -->|pull| VideoQ
    VideoW -->|InvokeEndpoint| SageMaker
    SageMaker -->|read segment, write result| OutputBucket
    VideoW -->|write| SegCompl
    SegCompl -->|DynamoDB Stream| Lambda
    Lambda -->|send job_id| ReassQ
    MediaW -->|pull| ReassQ
    MediaW -->|read/write| OutputBucket
    MediaW -->|read| SegCompl
    ECS -.->|pull images| ECR
```

**DynamoDB tables and access patterns:**

- **Jobs:** PK `job_id` (String). Attributes: `mode`, `status`, `created_at`, `total_segments`, `completed_at`, etc. **GSI** `status-completed_at`: PK `status`, SK `completed_at` (Number, Unix timestamp) for "list completed jobs" with descending sort and pagination.
- **SegmentCompletions:** PK `job_id`, SK `segment_index`. Attributes: `output_s3_uri`, `completed_at`. Query by `job_id` returns segments in order for reassembly.
- **ReassemblyTriggered:** PK `job_id` (String). Attributes: `triggered_at` (Number, Unix timestamp), `ttl` (Number, optional). Used for reassembly Lambda idempotency and media-worker lock (conditional write so only one worker runs reassembly per job). Enable **DynamoDB TTL** on `ttl`; set e.g. `ttl = triggered_at + (90 * 86400)` (90 days) so old rows are expired for cost and clarity.

**Access patterns:** (1) List completed jobs: query GSI `status-completed_at` with `status = 'completed'`, `ScanIndexForward = false`, pagination via `Limit` and `ExclusiveStartKey`. (2) Get/update job by `job_id`. (3) Query SegmentCompletions by `job_id`; (4) Conditional write to ReassemblyTriggered by `job_id`.

**Job status lifecycle:** Jobs move through the following statuses. **`created`** — set by web-ui when the job is created (DynamoDB put). **`chunking_in_progress`** — set by the media-worker when it starts processing the chunking message (optional but recommended so the "chunking failure recovery" janitor can find stuck jobs). **`chunking_complete`** — set by the media-worker in a single atomic UpdateItem when chunking finishes (`total_segments` and `status: chunking_complete`). **`completed`** — set by the media-worker (reassembly) after it successfully writes `final.mp4` and updates the Job record. Only DynamoDB is authoritative for status; no separate state store.

**Reassembly state:** The **Lambda** (reassembly trigger) performs a **conditional create** on **ReassemblyTriggered** (item must not exist) when `count(SegmentCompletions) == total_segments` and Job has `status: chunking_complete`; on success it sends `job_id` to the Reassembly queue. The **media-worker** (reassembly thread) uses the same table for a per-job lock: before concat it does a **conditional write** (e.g. set `reassembly_started_at` only if the item exists and that field is absent) so only one worker runs reassembly for that job; then it updates the Job to `status: completed`. So: Lambda writes "triggered" (idempotency); worker writes "started" and later Job "completed".

1.  **Storage (S3) and key layout:**
    - **Input bucket** (`s3://input-bucket/`): User uploads full MP4 to `input/{job_id}/source.mp4`. **S3 event notifications** are configured for **`s3:ObjectCreated:*`** (e.g. Put, CompleteMultipartUpload). Use **two S3 event notifications** (or prefix/suffix filters) so routing is explicit: (1) **prefix `input/`**, suffix `.mp4` → **chunking SQS queue**; (2) **prefix `segments/`**, suffix `.mp4` → **video-worker SQS queue**. No Lambda. Duplicate S3 events are possible and are handled by idempotent processing (deterministic keys and overwrites). The **media-worker** uploads segment files to the **same bucket** under the **canonical segment key** `segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4` (e.g. `segments/job-abc/00042_00100_anaglyph.mp4`); those uploads trigger (2) and go to the video-worker queue (see S3 → video-worker path below).
    - **Output bucket** (`s3://output-bucket/`): The **SageMaker** endpoint writes segment outputs to `jobs/{job_id}/segments/{segment_index}.mp4` (at the video-worker's request, passing the canonical output URI); the **video-worker** writes only the SegmentCompletion record to DynamoDB. The **media-worker** (reassembly) writes the final file to `jobs/{job_id}/final.mp4`. An **S3 lifecycle rule** on this bucket expires objects under the `jobs/*/segments/` prefix after **1 day**; `jobs/{job_id}/final.mp4` is not affected.
    - **Summary:** One input bucket (prefixes `input/`, `segments/`); one output bucket (prefix `jobs/`). All keys are deterministic so idempotency and routing are straightforward.
2.  **Orchestration (SQS + ECS):**
    - **Two S3 event flows (both S3 → SQS direct, no Lambda):** (1) **Full-file upload** → S3 event notification → **chunking queue** → media-worker (parses `job_id` from key and fetches `mode` from DynamoDB). (2) **Segment-file upload** (by media-worker) → S3 event notification → **video-worker queue** (see S3 → video-worker path below).
    - **Application Auto Scaling** scales the **media-worker** ECS service on chunking + reassembly queue depth and the **video-worker** ECS service on the video-worker queue depth. GPU inference runs on a **SageMaker** real-time endpoint (e.g. `ml.g4dn.xlarge` or `ml.g5.xlarge`); scale the endpoint or use SageMaker Serverless as needed.
    - **Capacity (single region):** **Video-worker SQS visibility timeout** must be at least **2–3×** the expected end-to-end segment processing time (video-worker → SageMaker invoke → SageMaker writes to S3), e.g. 15–20 minutes for ~5 min segments, so messages do not become visible before the pipeline finishes. **Multi-region** is not in scope for now (single-user / personal use); add only if needed for availability.
3.  **S3 event → video-worker path:**
    - **S3 → SQS direct only** (no Lambda). Segment objects uploaded by the media-worker trigger S3 event notifications to the **video-worker SQS queue**; the message is the raw S3 event (bucket, key). The **segment key parser is implemented only in `shared-types`**; the video-worker (and media-worker when building keys) calls that library. No duplicate parsing logic in workers. The parser takes bucket + key and returns the canonical payload (`job_id`, `segment_index`, `total_segments`, `mode`, `segment_s3_uri`).
    - **Duplicate S3 events:** Processing is **idempotent**. The SageMaker endpoint writes output to the deterministic path (`jobs/{job_id}/segments/{segment_index}.mp4`) and the video-worker writes SegmentCompletions once per segment; duplicate events may cause duplicate messages but reprocessing overwrites the same segment output and does not corrupt state.

```mermaid
flowchart LR
    subgraph Media
        MW[media-worker]
    end
    subgraph S3Events
        S3Seg[(S3 segment objects)]
    end
    subgraph VideoPipeline
        VQ[video-worker queue]
        VW[video-worker]
    end

    MW -->|upload segments| S3Seg
    S3Seg -->|S3 event notification| VQ
    VQ --> VW
```

4.  **Initial chunking (packages/media-worker — chunking):**
    - **Media-worker** handles chunking in one thread: **chunk** (ffmpeg, keyframe-aligned, e.g. ~50MB / ~5 min) and **upload** segment files to S3. Does **not** publish segment messages to SQS; it only writes segment objects. Segment keys and/or object metadata carry job_id, segment_index, total_segments, mode for the S3 → video-worker path.
    - **Chunking message (input source):** The chunking queue receives the **raw S3 event** (bucket, key). The **media-worker** (chunking thread) extracts the **input S3 URI** from the event, **parses `job_id`** from the key (`input/{job_id}/source.mp4`), **fetches `mode`** from the DynamoDB Jobs table, then **updates the Job to `status: chunking_in_progress`** (so recovery tools can find stuck jobs), downloads the source, runs ffmpeg to split, and uploads segments to S3 using the **canonical segment key** `segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4`. After chunking completes, the worker performs a **single atomic DynamoDB UpdateItem** that sets **`total_segments`** and **`status: chunking_complete`** (and optionally `chunking_completed_at`) on the Job record in one operation. Use a condition (e.g. `status = chunking_in_progress` or `created`) so the final update only applies when the job is in the expected state.
    - **Failure and retries:** Chunking is **idempotent**: segment keys are deterministic (the canonical format above). On failure, the message returns to the queue after visibility timeout and is retried; the worker may re-upload and overwrite the same segment objects. Downstream (video-worker) handles duplicate segment events via idempotent segment processing. No explicit cleanup of partial segments is required for correctness; optional enhancement is a "chunking started" marker and cleanup on retry.
5.  **The Video Worker (Thin client + SageMaker):**
    - The video-worker (Fargate) pulls a message, parses the segment payload via shared-types, and builds the canonical output URI `s3://output-bucket/jobs/{job_id}/segments/{segment_index}.mp4`. It calls **SageMaker InvokeEndpoint** with JSON `{"s3_input_uri": "<segment_uri>", "s3_output_uri": "<canonical_output_uri>"}`. The **SageMaker endpoint** (custom container running StereoCrafter) reads the segment from S3, runs the two-stage pipeline (depth splatting → inpainting), and **writes the stereo segment directly to the given s3_output_uri**. The video-worker does not upload segment bytes; after a successful response it writes the **SegmentCompletion** record to DynamoDB. **Sizing:** Segment processing time is dominated by SageMaker (e.g. a few minutes wall-clock per ~5 min segment on a typical GPU instance); set SQS visibility timeout and endpoint capacity accordingly (see IMPLEMENTATION_PLAN and StereoCrafter docs).
6.  **Job and segment model:**
    - **Job** = one movie conversion (one input file → one output 3D file). Has `job_id`, `mode` (anaglyph | sbs), etc.
    - **Segment** = one chunk of that movie (e.g. 50MB / ~5 min), produced by the media-worker as a **segment file** in S3. S3 events (or Lambda) produce one message per segment for the video-worker queue; message or object key/metadata carries `job_id`, `segment_index`, `total_segments`, segment S3 URI, `mode`.
    - **Standard SQS** (not FIFO) for higher throughput. Ordering enforced at reassembly by `segment_index`; workers process segments in any order.
7.  **Reassembly (DynamoDB Streams):**
    - The **SageMaker** endpoint writes segment outputs to `s3://output-bucket/jobs/{job_id}/segments/{segment_index}.mp4` (at the video-worker's request); the **video-worker** writes a record to the **SegmentCompletions** DynamoDB table (`job_id`, `segment_index`, `output_s3_uri`, `completed_at`). The table uses **`job_id` as partition key** and **`segment_index` as sort key**, so a Query by `job_id` returns segments in order and the media-worker can build the concat list without application-side sorting. **`total_segments`** and **`status: chunking_complete`** for a job are set by the **media-worker** (chunking) when it finishes (written to the Job record in DynamoDB). The reassembly Lambda uses both: it triggers only when the Job has **chunking_complete** (and thus `total_segments` set) and the count of SegmentCompletions for that `job_id` equals `total_segments`.
    - **Reassembly trigger:** A **DynamoDB Stream** is attached to the SegmentCompletions table. A **Lambda** function is invoked on batches of new records. It processes each batch fully: for each distinct `job_id` in the batch, it fetches the Job record (`total_segments`, `status`) and counts SegmentCompletions for that `job_id`. It **only considers triggering when** the Job has `status: chunking_complete` and the count equals `total_segments`. When that condition holds, the Lambda performs a **conditional write** to the **ReassemblyTriggered** table (see DynamoDB tables below) only if the item does not exist; if the write succeeds, it sends `job_id` to the Reassembly SQS queue; if the condition fails (already triggered), it skips sending. **Idempotency:** DynamoDB Streams can deliver the same change more than once; the conditional write ensures at most one reassembly message per job. Set Lambda **timeout** (e.g. ≥ 30 s) and **reserved concurrency** (e.g. low) to handle batches and avoid thundering herd when many segments complete at once. **Future improvement:** Consider replacing the Lambda with an in-cluster consumer (e.g. a Deployment that reads DynamoDB Streams or polls) to reduce Lambda invocation volume and to simplify a future GCP port (e.g. Firestore change listeners or a poller).
    - **Chunking failure recovery:** If the media-worker crashes after uploading segments but before writing `total_segments` / `chunking_complete`, reassembly would never trigger. **V1 — manual recovery:** Document the procedure: list S3 prefix `segments/{job_id}/`, derive `total_segments` from the max `segment_index` in the key pattern (or key parser in shared-types), then perform a single DynamoDB UpdateItem on the Job to set `total_segments` and `status: chunking_complete` so the existing Stream logic can trigger reassembly. **Future enhancement:** A small periodic "janitor" (e.g. Lambda on schedule or in-cluster CronJob) that finds Jobs stuck in `chunking_in_progress` (or similar) older than a threshold, lists `segments/{job_id}/` in S3, infers `total_segments` consistently, and updates the Job as above.
    - The **media-worker** (reassembly thread, same ECS cluster, CPU-only Fargate service scaled by Application Auto Scaling on chunking and reassembly queues) pulls the message, **builds the segment list from DynamoDB**: it queries **SegmentCompletions** by `job_id` ordered by `segment_index`, and uses `output_s3_uri` (or the deterministic path `jobs/{job_id}/segments/{segment_index}.mp4`) to build the ffmpeg concat list. It does **not** discover segments by listing S3 (to avoid races). Optionally it verifies each segment object exists in S3 before concat. Output: `s3://output-bucket/jobs/{job_id}/final.mp4`. After success, the worker **updates the Job record to `status: completed`** (and optionally `final_s3_uri`, `completed_at`) so "list available movies" uses DynamoDB as source of truth. **Segment object retention:** Segment objects in the output bucket (`jobs/{job_id}/segments/`) are retained for **1 day** via an **S3 lifecycle rule** (expire after 1 day); `jobs/{job_id}/final.mp4` is not affected. **Idempotency:** Standard SQS can deliver duplicate or out-of-order messages. The reassembly worker uses the **ReassemblyTriggered** table as a lock: the Lambda has already created the item (conditional create). The worker does a **conditional update** (e.g. set `reassembly_started_at` only if the item exists and that attribute is absent) so only one worker proceeds; if the update fails (another worker started), it skips and deletes the message. On success it builds the concat list, writes `final.mp4`, updates the Job to `status: completed`, then deletes the message. It also checks if `final.mp4` already exists and skips concat if so (updating Job status if needed). Lambda is not used for the concat itself because the final file can be large—a CPU worker is simpler and more predictable.

```mermaid
flowchart LR
    subgraph VideoWorkers
        VW[video-worker]
    end
    subgraph DDB
        SC[(SegmentCompletions)]
    end
    subgraph Stream
        DS[DynamoDB Stream]
        Lambda[Lambda]
    end
    subgraph Reassembly
        RQ[Reassembly queue]
        RW[media-worker]
    end

    VW -->|write record| SC
    SC --> DS
    DS --> Lambda
    Lambda -->|last segment?| RQ
    RQ --> RW
```

**End-to-end job pipeline (life of a job):**

```mermaid
flowchart LR
    subgraph Upload["1. Upload"]
        A[User] -->|presigned URL| B[input bucket]
    end
    subgraph Chunk["2. Chunking"]
        B -->|S3 event| C[chunking queue]
        C --> D[media-worker]
        D -->|segment files| E[(segments S3)]
    end
    subgraph Video["3. 3D processing"]
        E -->|S3 event| F[video-worker queue]
        F --> G[video-workers]
        G -->|InvokeEndpoint| SM[SageMaker]
        SM -->|segment outputs| H[(output bucket)]
        G -->|record| I[(SegmentCompletions)]
    end
    subgraph Reass["4. Reassembly"]
        I -->|DynamoDB Stream| J[Lambda]
        J -->|last segment| K[reassembly queue]
        K --> L[media-worker]
        L -->|concat| M[final.mp4]
    end
    subgraph Consume["5. Consume"]
        M --> H
        A -->|list / presigned GET| N[web-ui]
        N --> H
    end

    Upload --> Chunk --> Video --> Reass --> Consume
```

8.  **Web UI (ECS):** The **FastAPI app** runs as an ECS Fargate service. It serves the dashboard and an API (FastAPI routes) that uses the **AWS SDK** (boto3) with **IAM task role** to list S3/DynamoDB and generate presigned upload and playback URLs. Exposed via an **ALB** in front of the service. **Authentication:** No auth for now (single-user / personal use). No VPN; access is as configured (e.g. ALB). Add auth (e.g. Cognito OIDC) when opening to more users. **Multi-user:** Supporting multiple users would require introducing a **`user_id`** (or similar) in the job and segment data model and in IAM so presigned URLs and API access are scoped per user.

---

📦 Build, Registry, and Deployment

**Stages are split:** Terraform provisions AWS infra (S3, SQS, DynamoDB, ECR, Lambda, **ECS cluster**, **task definitions**, **services**, **ALB**). Workload updates are deployed by **building and pushing** images to ECR, then **updating ECS services** (e.g. `aws ecs update-service --force-new-deployment` or Terraform with an image tag variable).

**ECS workloads:**

```mermaid
flowchart TB
    subgraph ECS["ECS Cluster"]
        ALB[ALB]
        subgraph Web["Web"]
            WebUI[web-ui Fargate]
        end
        subgraph Workers["Workers"]
            MediaW[media-worker Fargate\nscale on SQS]
            VideoW[video-worker Fargate\nscale on SQS]
        end
        ALB --> WebUI
    end

    ChunkQ[chunking queue] -.->|scale| MediaW
    ReassQ[reassembly queue] -.->|scale| MediaW
    VideoQ[video-worker queue] -.->|scale| VideoW
```

**Build and deploy pipeline:**

```mermaid
flowchart LR
    subgraph Infra["Infra"]
        Tf[Terraform apply\nS3, SQS, DDB, ECR, Lambda\nECS cluster, tasks, services\nSageMaker, ALB]
    end
    subgraph Build["Build"]
        B1[build web-ui image]
        B2[build media-worker image]
        B3[build video-worker image]
        B4[build SageMaker inference image]
    end
    subgraph Push["Push"]
        ECR[(ECR\nsame tag)]
    end
    subgraph Deploy["Deploy"]
        Update[ECS force-new-deployment\nor update task def tag]
    end

    Tf --> Build
    Build --> Push
    Push --> Update
```

1.  **Registry (ECR):** Terraform creates **AWS ECR** repositories (one per image: `web-ui`, `media-worker`, `video-worker`, and the **SageMaker inference image** e.g. `stereocrafter-sagemaker`). All images are pushed to ECR so ECS (and SageMaker) in the same account/region can pull them without extra configuration.
2.  **Build and push:** Each package (web-ui, media-worker, video-worker) is packaged into a **Docker image** and pushed to its ECR repo. The **SageMaker inference container** (StereoCrafter) is built and pushed to its ECR repo; Terraform creates/updates the SageMaker model and endpoint. See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for order of operations (e.g. create Secrets Manager secret for HF token → Terraform apply → build/push inference image → create/update endpoint → deploy video-worker). Builds can run **in parallel** (e.g. one CI job per package). Use a **single image identifier per release** (e.g. **git SHA** or pipeline run ID): every image is tagged with the same value (e.g. `abc123`) so the deploy step only needs one tag. When using CI, the deploy step should run only after **all** image build/push jobs succeed.
3.  **Deploy ECS and SageMaker:** Task definitions reference ECR image URIs and a tag (e.g. from a Terraform variable). After building and pushing new images (including the SageMaker inference image when updated), create or update the **SageMaker** endpoint as needed, then run **force new deployment** on each ECS service so tasks pull the new image. Full pipeline: **Terraform apply** (data plane + ECS cluster, task definitions, services, SageMaker model/endpoint config/endpoint, ALB) → **build + push images** (web-ui, media-worker, video-worker, and SageMaker inference image) → **create/update SageMaker endpoint** (if inference image changed) → **force new deployment** on ECS services. See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for details.

---

🛠️ Handling Spot Terminations & Large Files

To ensure **"Very Good Error Handling"** for large video files:

- **Chunking strategy:** Initial chunking is done by the **media-worker** (see above): ffmpeg splits the source into keyframe-aligned segments (~50MB / ~5 min) and uploads them to S3; S3 events on segment uploads drive video-worker processing. Segment size limits the "blast radius" of a Spot interruption to roughly one segment (e.g. 5 minutes of work).
- **Spot on ECS:** ECS handles Spot interruption: tasks are stopped and messages return to SQS (segment-level retry). The video-worker runs on Fargate (no Spot at the task level). GPU capacity is on **SageMaker**; you can configure the endpoint for Spot or on-demand instances as needed.
- **Atomic Uploads:** Use S3 Multipart Uploads for the final 3D file (media-worker → output bucket) to handle network flakiness during the upload of large assets.
- **Large user uploads:** **V1:** Support only **single presigned PUT** for the source file. **Max file size for V1: ~500 MB** (S3 allows up to 5 GB single PUT, but browser and timeouts suggest this practical limit). **Later enhancement:** For larger files, the API can support **S3 multipart upload** (initiate multipart upload → presigned URLs per part → complete multipart upload); the object key remains `input/{job_id}/source.mp4`, so the same S3 event notification triggers chunking.
- **Checkpointing and resumability (V1 — simple):** **Segment-level retry only.** If a worker is interrupted mid-segment (e.g. Spot reclaim), the message returns to the queue after visibility timeout and is **reprocessed from the start**; no frame-level checkpoint. At ~5 min per segment, losing one segment's work is acceptable and keeps the design simple. Optionally add a **metric** (e.g. segment retry or reprocess count) for visibility. Frame-level resume (checkpoint on SIGTERM, resume from `start_frame`) is **out of scope for V1**; consider as a future enhancement if needed.
- **DynamoDB usage:** Use **separate tables** for distinct concerns: (1) **SegmentCompletions**—segment completion tracking for reassembly (`job_id`, `segment_index`, `output_s3_uri`, `completed_at`); (2) **ReassemblyTriggered**—one row per `job_id` for reassembly Lambda idempotency and media-worker lock (see DynamoDB tables below). Do not mix completion state with liveness in one table. **Future:** WorkerHeartbeats (`job_id`, `segment_index`, `worker_id`, `last_heartbeat`) for progress UI and optional frame-level resume; not required for V1.

---

💰 Cost

- **Main levers:** **SageMaker** endpoint instance cost (GPU, e.g. ml.g4dn/ml.g5), S3 storage and egress, DynamoDB read/write, Lambda invocations, Fargate. Segment sizing (~50MB / ~5 min) keeps cost predictable for batch video work.
- **Guardrails:** Set **ECS service max capacity** (e.g. max tasks for video-worker) and **SageMaker** endpoint instance count (or use Serverless) to cap scale. **SQS:** Each main queue (chunking, video-worker, reassembly) has a **Dead-Letter Queue (DLQ)** and a **max receive count** (e.g. 3–5); after that, messages move to the DLQ. Add a **CloudWatch alarm** on "number of messages in each DLQ" (e.g. > 0) so failed messages are visible and do not spin forever. Tag resources (e.g. `project=stereo-spot`) for billing visibility; optionally set **AWS Budgets** alerts.

---

🔒 Security and Operations

- **IAM:** ECS tasks use **task roles** (not IRSA) for S3, SQS, and DynamoDB; no long-lived access keys.
- **Network:** Fargate tasks run in **private subnets**; ALB in **public subnets**. Use an **S3 VPC endpoint** (gateway) to avoid NAT and improve throughput and cost.
- **Secrets:** The **Hugging Face token** for the SageMaker inference container (gated model downloads at startup) is stored in **AWS Secrets Manager** and injected into the endpoint via Terraform. Store other API keys or model artifacts in Secrets Manager or S3 with restricted access; mount or pull at runtime.
- **Observability:** Use **CloudWatch** for worker logs and metrics; optional **X-Ray** for tracing.
  - **V1 observability:** Expose or derive a metric for "segments completed / total_segments" per job (e.g. from SegmentCompletions and Job metadata). Add a **CloudWatch alarm** (or equivalent) when no new segment has completed for a job for a configured threshold (e.g. N minutes) to detect stuck jobs.
  - **Job-level visibility:** SegmentCompletions (and job metadata) are the source of truth for progress.
  - **Reassembly:** Monitor Reassembly SQS queue depth and media-worker error logs; alert on depth above threshold or repeated failures.
  - **Tracing (optional):** Propagate `job_id` and `segment_index` in logs and X-Ray so a single job can be traced from chunking → video-worker → reassembly.

**Risks and follow-ups (to look into later):**

- **Multiple uploads per job_id:** If the user uploads again to the same `input/{job_id}/source.mp4`, S3 overwrites the object and sends a new event to the chunking queue. Chunking is **idempotent** (deterministic segment keys), so the job is re-chunked and video-worker/reassembly behaviour are unchanged. For V1 we do not prevent or deduplicate this. Optional later: enforce a single upload per job (e.g. conditional write on a `source_uploaded_at` attribute) or document that re-upload means re-processing the job.
- **Segment key format and parsing drift:** The segment key format and **parser are implemented only in `shared-types`**; media-worker and video-worker both use that library—no duplicate parsing logic. Add integration tests that round-trip key generation and parsing so both sides stay in sync.

---

🔄 Migration Path to Google Cloud (GCP) 

The pipeline uses **shared-types** and **cloud abstractions** (JobStore, QueueSender/Receiver, ObjectStorage); application and worker code stay the same. Moving to GCP is feasible with new Terraform and adapters:

- **ECS → Cloud Run and/or GKE:** Same container images; GCP Terraform (e.g. `packages/google-infra`) would provision **Cloud Run** services or **GKE** with similar env vars. **SageMaker → Vertex AI** (or similar) for the StereoCrafter inference endpoint; video-worker would call the GCP endpoint instead of InvokeEndpoint. No change to app logic beyond config.
- **SQS → Pub/Sub:** Queue semantics and IAM differ; implement a GCP adapter behind the same queue interface; reassembly trigger would use Pub/Sub or equivalent.
- **S3 → GCS:** Implement GCP object-storage adapter; both use similar SDK patterns.
- **DynamoDB → Firestore:** Implement GCP job and segment-completion stores behind existing interfaces.
- **Terraform:** Keep `packages/aws-infra-setup` and `packages/aws-infra` for AWS. Add `packages/google-infra-setup` and `packages/google-infra` using the Google provider and the same nx-terraform pattern when migrating.
