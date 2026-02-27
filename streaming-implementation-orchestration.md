# Streaming implementation plan: Separate prefix, single queue (orchestration)

Detailed implementation plan for **separate S3 prefix** for stream chunks reusing the **existing video_worker queue**: event-driven invocation per chunk, no reassembly, optional stream_sessions store. Batch pipeline remains unchanged. Stream and batch segments are the same kind of work (inference on input MP4 → output MP4); only key format and completion handling differ.

**Current split (batch):** **Video-worker** consumes the `video_worker` queue and runs inference only (upload segment to output bucket; backpressure via output_events queue). **Job-worker** consumes the `job_status_events` queue (S3 output-bucket notifications) and handles SegmentCompletions, job status updates, and reassembly triggers. Streaming reuses the same video-worker and **same queue**.

**Decisions:** Streaming API (session create/end, playlist) lives in the **web-ui** package; no separate streaming backend. The **video-worker** consumes the **single** `video_worker` queue; messages can be either batch segment keys (`segments/`) or stream chunk keys (`stream_input/`). The worker **branches on key prefix** and **shares the existing inference semaphore** (stream and batch share SageMaker capacity; acceptable for v1). **Job-worker** is not used for stream completion (see SageMaker async below); no job_status_events for stream_output/. No session-status endpoint.

---

## 1. Goals and constraints

- **Input:** Client uploads chunks to `stream_input/{session_id}/chunk_{index:05d}.mp4` (see client capture plan). Chunks are A/V (e.g. H.264 + AAC). S3 emits object-created events.
- **Output:** Inference writes SBS (or anaglyph) with audio to `stream_output/{session_id}/seg_{index:05d}.mp4`. Playlist service lists this prefix to build HLS (see playback plan).
- **No** SegmentCompletion, no reassembly trigger, no job row for streams (or optional stream_sessions table only).
- **Same** SageMaker/inference API: one invocation per chunk with `input_uri` and `output_uri`.

---

## 2. Components to add or change

| Component | Change |
|-----------|--------|
| **S3 input bucket** | New event notification: prefix `stream_input/`, suffix `.mp4` → **same** `video_worker` queue (no new queue). |
| **SQS** | No new queue. Add S3 queue policy so input bucket can SendMessage to `video_worker` for the new prefix (or reuse existing policy if it already allows the whole bucket). |
| **Video-worker** | Same process, **single** consumer for `video_worker` queue. On each message, parse key: if `stream_input/` → stream path; else → batch path. **Batch path (unchanged):** parse segment key → invoke SageMaker → write to output bucket; job-worker (via `job_status_events`) handles SegmentCompletion and reassembly. **Stream path:** parse stream key → invoke SageMaker → write to `stream_output/...`; no SegmentCompletion, no reassembly. **Shared** inference semaphore for both. For SageMaker async, stream invocations are recorded in the invocation store so the output_events loop can release the semaphore (see §4.7). |
| **Job-worker** | When processing `sagemaker-async-responses/` events, **skip** records that are for stream (e.g. record has `session_id` or type=stream): only delete from invocation store; do not write SegmentCompletion or trigger reassembly. Otherwise unchanged. |
| **DynamoDB (optional)** | New table `stream_sessions`: session_id (PK), created_at, mode, ended_at. Used by web-ui for session create/end and by playlist for `#EXT-X-ENDLIST`. |
| **Web-ui** | New routes: create stream session (return session_id, **temporary AWS credentials** 1 h, playlist_url), end stream session. No per-chunk upload URL endpoint. |

---

## 3. Phase 1: AWS infra (S3 events only; no new queue)

### 3.1 S3 event: stream_input → video_worker (same queue)

**File:** `packages/aws-infra/s3_events.tf`

- In `aws_s3_bucket_notification.input`, add a third `queue` block:
  - `queue_arn` = `aws_sqs_queue.video_worker.arn` (same queue as batch segments)
  - `events` = `["s3:ObjectCreated:*"]`
  - `filter_prefix` = `"stream_input/"`
  - `filter_suffix` = `".mp4"`

- Ensure `depends_on` includes the existing `aws_sqs_queue_policy.video_worker_allow_s3` (input bucket already has permission to send to video_worker; if the policy is scoped by prefix, extend it to allow `stream_input/` as well, or keep a single bucket-level condition).

**Note:** S3 allows multiple notifications per bucket; existing `input/` → chunking and `segments/` → video_worker stay as-is. No overlap with `stream_input/`. No new SQS queue or DLQ.

### 3.2 Output bucket: stream_output prefix and IAM

No new S3 resources: inference will write to the **existing output bucket** with keys `stream_output/{session_id}/seg_{index:05d}.mp4`. **Explicit step:** Verify the SageMaker execution role (or the role that writes async results) has `s3:PutObject` on the output bucket prefix `stream_output/*`. If the current policy allows only `jobs/*` and `sagemaker-async-*`, add a minimal IAM statement for `stream_output/*` in `packages/aws-infra` (e.g. SageMaker role or ECS task role policy).

### 3.3 Optional: stream_sessions DynamoDB table

**File:** `packages/aws-infra/dynamodb.tf` (or new `dynamodb_stream_sessions.tf`)

- Table: `stream_sessions`
  - PK: `session_id` (string).
  - Attributes: `created_at` (string, ISO), `mode` (string, e.g. "sbs"), `ended_at` (string, ISO, optional).
- No DynamoDB streams needed unless you want event-driven cleanup.
- TTL (optional): attribute `ttl` (number, Unix timestamp) for automatic deletion of old sessions; set when session is ended or after N hours.

---

## 4. Phase 2: Worker logic (stream chunk consumer)

### 4.1 Message format

Message body = standard S3 event notification JSON (same as batch path): `Records[0].s3.bucket.name`, `Records[0].s3.object.key`. Key will look like `stream_input/abc-session-id/chunk_00042.mp4`.

### 4.2 Key parser (stream)

**Location:** `packages/shared-types` or `packages/video-worker`.

- Add a function e.g. `parse_stream_chunk_key(bucket: str, key: str) -> StreamChunkPayload | None`.
- Convention: key = `stream_input/{session_id}/chunk_{index:05d}.mp4`. Regex or split: extract `session_id`, `index`. Validate index is non-negative.
- Return type: e.g. `StreamChunkPayload(session_id, chunk_index, input_s3_uri, output_s3_uri, mode)`. `output_s3_uri` = `s3://{output_bucket}/stream_output/{session_id}/seg_{index:05d}.mp4`. `mode` from session config (see below) or default `"sbs"`.

**Mode:** Either (a) store mode in stream_sessions and worker looks it up by session_id, or (b) encode mode in the key or S3 object metadata. Simplest: store in stream_sessions; worker reads once per message. **When stream_sessions is optional or the session row is missing:** Use a fixed default **mode = "sbs"** and do not fail; the worker must not depend on the table being present.

### 4.3 Worker branch: stream vs batch

**File:** `packages/video-worker/src/video_worker/s3_event.py` (or new `stream_event.py`)

- When parsing the S3 event body, first check if key starts with `stream_input/`.
  - If **yes:** call `parse_stream_chunk_key(bucket, key)`. If result is not None, return a union type or a dedicated “stream payload” so the main loop can branch.
  - If **no:** keep existing `parse_segment_key(bucket, key)` for batch.

**File:** `packages/video-worker/src/video_worker/inference.py` (or new `stream_inference.py`)

- In `process_one_message` (or equivalent):
  - If payload is **stream chunk:** call new `process_stream_chunk(payload, storage, output_bucket, stream_sessions_store?)`. Do **not** write SegmentCompletion, trigger reassembly, or touch job_store (job-worker is only for the batch/job path).
  - If payload is **batch segment:** keep current logic unchanged (invoke SageMaker, upload segment to output bucket; SegmentCompletion and reassembly are handled by job-worker when it sees output-bucket events on `job_status_events`).

### 4.4 process_stream_chunk

- Input: `StreamChunkPayload` (session_id, chunk_index, input_s3_uri, output_s3_uri, mode).
- Optional: resolve `mode` from stream_sessions table if not in payload.
- Invoke SageMaker (or HTTP/stub) with:
  - `input_uri` = payload.input_s3_uri
  - `output_uri` = payload.output_s3_uri
  - `mode` = payload.mode
- Same invocation path as batch (SageMaker async or sync). Inference container is unchanged; it only cares about input/output URIs and mode.
- On success: optional observability (e.g. CloudWatch metric “StreamSegmentCompleted”, or write to a lightweight “stream_segment_done” store). Do **not** write to SegmentCompletions or trigger reassembly.
- On failure: log, re-raise or return False so the message can be retried or sent to DLQ per SQS config.
- **Idempotency:** Overwriting `stream_output/{session_id}/seg_{index:05d}.mp4` on retry is idempotent and acceptable; no reassembly or job state, so no extra idempotency mechanism is required.

### 4.5 Queue consumer (single queue, single loop)

**Approach:** Video-worker keeps **one** inference loop consuming the **single** `video_worker` queue. The same process also runs the **output_events** loop (for SageMaker backpressure). No second queue or second receiver.

- On each message from `video_worker`: parse S3 event, get bucket and key. If key starts with `stream_input/` → parse as stream chunk and call `process_stream_chunk`; else → parse as batch segment and use existing batch path. Both paths use the same storage, SageMaker client, and **the same inference semaphore** (stream and batch share the configured in-flight limit). Under load, stream and batch contend for SageMaker slots; acceptable for v1.

### 4.6 IAM

No new queue permissions: video-worker already has `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` on the `video_worker` queue. S3 and SageMaker permissions are shared for batch and stream. Ensure input bucket S3 notification policy allows S3 to send `stream_input/` events to the video_worker queue (see §3.1).

### 4.7 SageMaker async: invocation store and job-worker skip for stream

When **SageMaker async** is used, the video-worker records each invocation in **InferenceInvocationsStore** (keyed by SageMaker `output_location`). The **output_events** queue receives `sagemaker-async-responses/` events; the video-worker's output_events loop uses the store to release the **inference semaphore** (backpressure). The **job-worker** consumes the same events via **job_status_events** and writes SegmentCompletion + triggers reassembly for batch.

For **stream** chunks, the video-worker must still **put** an entry in the invocation store when invoking SageMaker (so the output_events loop can release the semaphore when the async result arrives). The same S3 event will also be processed by the job-worker. To avoid writing SegmentCompletions or triggering reassembly for stream:

- **Store:** Extend the invocation store (or the put contract) so stream invocations are distinguishable from batch, e.g. store an optional `session_id` (and no `job_id`) or a sentinel `job_id` / type such as `"__stream__"` or `type: "stream"`.
- **Video-worker stream path:** When invoking SageMaker for a stream chunk, call `invocation_store.put(output_location, ...)` with the chosen convention (e.g. `job_id="__stream__"`, `session_id=payload.session_id`, or a dedicated stream put method).
- **Job-worker:** When handling a `sagemaker-async-responses/` event, after `invocation_store.get(s3_uri)`, if the record is for a stream (e.g. has `session_id`, or `job_id == "__stream__"`, or `type == "stream"`): **do not** write SegmentCompletion or call `maybe_trigger_reassembly`; **do** delete the record from the invocation store (so the table does not fill with stream entries). Then return (ack the message).

---

## 5. Phase 3: Web-ui API (stream session create/end, in web-ui package)

### 5.1 Create stream session

**Route:** `POST /stream_sessions`

- Body: `{ "mode": "sbs" }` (or "anaglyph").
- Generate `session_id` (e.g. UUID or nanoid).
- Optional: write to DynamoDB stream_sessions: `session_id`, `created_at`, `mode`, `ended_at` = null.
- **Temporary credentials:** Use STS **AssumeRole** (or GetFederationToken) with a role/policy that allows only `s3:PutObject` on `stream_input/{session_id}/*` for the input bucket. Request **1 hour** session duration (`DurationSeconds=3600`). This avoids any per-chunk or batch URL requests; the client uses one set of credentials for all uploads.
- Build response:
  - `session_id`
  - `playlist_url`: `https://{request.host}/stream/{session_id}/playlist.m3u8`
  - `upload`: `{ "access_key_id": "...", "secret_access_key": "...", "session_token": "...", "bucket": "<input-bucket>", "region": "...", "expires_at": "..." }` (or equivalent so the client can construct an S3 client). Expiry = 1 h from now.

### 5.2 End stream session

**Route:** `POST /stream_sessions/{id}/end` or `PATCH /stream_sessions/{id}` with body `{ "ended": true }`.

- Set `ended_at` = now in stream_sessions (if table exists).
- Return 204 or 200. Playlist endpoint will use `ended_at` to add `#EXT-X-ENDLIST`.

---

## 6. Implementation order

1. **Infra:** Add S3 event for `stream_input/` → **video_worker** (same queue). Verify/extend input bucket policy if needed. Verify SageMaker execution role has `s3:PutObject` on output bucket `stream_output/*`; add IAM if needed. Deploy. (No new queue; no change to job_status_events or job-worker.)
2. **shared-types or video-worker:** Add `parse_stream_chunk_key` and `StreamChunkPayload`. Wire stream_sessions table (optional) and mode resolution (default "sbs" when table absent).
3. **video-worker:** Branch in existing inference loop on key prefix; add `process_stream_chunk`. For SageMaker async, extend invocation store put for stream (e.g. session_id or sentinel job_id). **Job-worker:** When processing `sagemaker-async-responses/`, skip stream records (delete from store only; no SegmentCompletion/reassembly).
4. **Web-ui:** Add stream_sessions table (optional), routes create (with temporary credentials, 1 h) and end. Implement STS AssumeRole (or GetFederationToken) with policy scoped to `stream_input/{session_id}/*`.
5. **Playback:** Implement `GET /stream/{session_id}/playlist.m3u8` (see playback plan) using `stream_output/{session_id}/` and optional `ended_at` from stream_sessions.
6. **E2E test:** Create session (get temporary credentials) → upload 2–3 chunks with S3 PUT using those credentials → end session → check playlist and segment objects in output bucket; run inference via worker and confirm seg_*.mp4 appear.
7. **Docs:** Update `packages/stereo-spot-docs` (e.g. "Streaming" or "Live pipeline" under architecture) so the stream path is documented and kept in sync.

---

## 7. File checklist

| File / area | Action |
|-------------|--------|
| `aws-infra/s3_events.tf` | Add queue block: prefix `stream_input/`, suffix `.mp4` → **video_worker** (same queue) |
| `aws-infra` (IAM) | Ensure SageMaker/execution role has `s3:PutObject` on output bucket `stream_output/*`; extend policy if needed |
| `aws-infra/dynamodb.tf` (optional) | stream_sessions table |
| `shared-types` or `video-worker` | StreamChunkPayload, parse_stream_chunk_key |
| `video-worker/s3_event.py` or new | Branch: stream_input/ vs segments/ (batch) keys |
| `video-worker/inference.py` | process_stream_chunk; branch in existing loop on key prefix; batch path unchanged |
| `video-worker/main.py` | No second queue; single inference loop (branch inside loop) |
| `aws-adapters` (invocation store) | Extend put/get for stream (e.g. session_id or type=stream); job-worker skip logic |
| `job-worker/job_status_events.py` | For sagemaker-async-responses/: if record is stream, delete from store only; no SegmentCompletion/reassembly |
| `web-ui/routers/` | New router or routes: stream_sessions create (return temp credentials), end |
| Adapters (if any) | stream_sessions_store_from_env for optional DynamoDB |
| `packages/stereo-spot-docs` | Add Streaming / Live pipeline section; keep in sync with this plan |

---

## 8. Observability

- **CloudWatch:** Video-worker queue depth (combined batch + stream; existing SQS metrics). Optional: custom metric “StreamSegmentCompleted” per session_id for stream-only visibility.
- **DLQ:** Existing `video_worker_dlq` receives failed messages for both batch and stream; alarm if message count > 0 (same pattern in `packages/aws-infra/cloudwatch.tf`). Inspect message body (key prefix) to distinguish stream vs batch when debugging.
- **Logs:** Log session_id and chunk_index in worker on start/success/failure for stream path correlation.
