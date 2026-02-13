# Shared types and cloud abstraction interfaces

The `packages/shared-types` library defines Pydantic models and **cloud-agnostic interfaces** for the stereo-spot pipeline. Application and worker code depend on these interfaces; concrete implementations (e.g. AWS DynamoDB, SQS, S3) are provided by adapter packages (e.g. `packages/aws-adapters`) and wired via configuration (e.g. `STORAGE_ADAPTER=aws`).

---

## Interfaces

### JobStore

**Methods:** `get(job_id)`, `put(job)`, `update(job_id, status=..., total_segments=..., completed_at=...)`, `list_completed(limit, exclusive_start_key=None)`.

**Purpose:** Single source of truth for job metadata (mode, status, total_segments, timestamps). Used for create job, update status after chunking/reassembly, and list completed jobs for the UI.

**Consumers:**

- **web-ui:** put (create job), get (job detail), list_completed (list page), update (not typically; workers update).
- **chunking-worker:** get (fetch mode), update (chunking_in_progress → chunking_complete + total_segments).
- **reassembly-worker:** get (total_segments, status), update (status=completed, completed_at).
- **reassembly-trigger (Lambda):** get (total_segments, status) to decide when to send to reassembly queue.

---

### SegmentCompletionStore

**Methods:** `put(completion)`, `query_by_job(job_id)`.

**Purpose:** Records each segment completion (output_s3_uri, completed_at). Query by job returns completions ordered by segment_index for reassembly.

**Consumers:**

- **video-worker:** put (after each segment is processed).
- **reassembly-trigger (Lambda):** query_by_job + count vs total_segments to trigger reassembly when last segment completes.
- **reassembly-worker:** query_by_job to build the concat list (no S3 list).

---

### QueueSender / QueueReceiver

**QueueSender:** `send(body)` — send one message (body as str or bytes).

**QueueReceiver:** `receive(max_messages=1)` → list of `QueueMessage` (receipt_handle, body); `delete(receipt_handle)` — delete after successful processing.

**Purpose:** Decouple producers and consumers (chunking queue, video-worker queue, reassembly queue). Same interface for SQS, Pub/Sub, etc.

**Consumers:**

- **chunking-worker:** QueueReceiver (chunking queue).
- **video-worker:** QueueReceiver (video-worker queue).
- **reassembly-worker:** QueueReceiver (reassembly queue).
- **reassembly-trigger (Lambda):** QueueSender (reassembly queue).

---

### ObjectStorage

**Methods:** `presign_upload(bucket, key, expires_in=3600)`, `presign_download(bucket, key, expires_in=3600)`, `upload(bucket, key, body)`, `download(bucket, key)`.

**Purpose:** Upload/download bytes and generate presigned URLs for direct browser/client access (upload source file, playback final file).

**Consumers:**

- **web-ui:** presign_upload (create job → upload URL), presign_download (playback URL).
- **chunking-worker:** download (source), upload (segment files).
- **video-worker:** download (segment), upload (segment output).
- **reassembly-worker:** download (segment outputs), upload (final.mp4).

---

## Implementation

- **AWS:** Implementations in `packages/aws-adapters` (DynamoDB for JobStore and SegmentCompletionStore, SQS for queues, S3 for ObjectStorage). Used when `STORAGE_ADAPTER=aws` (or equivalent).
- **GCP (future):** Implementations behind the same interfaces (e.g. Firestore, Pub/Sub, GCS) in a separate package; pipeline code stays unchanged.
