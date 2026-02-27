## Streaming implementation – execution plan

This file tracks the high‑level steps to implement the streaming feature across capture, orchestration, and playback.

Reference docs in the repo root:

- **Client capture**: [`streaming-implementation-client-capture.md`](./streaming-implementation-client-capture.md)
- **Orchestration / backend pipeline**: [`streaming-implementation-orchestration.md`](./streaming-implementation-orchestration.md)
- **Playback / HLS playlist**: [`streaming-implementation-playback-hls.md`](./streaming-implementation-playback-hls.md)

---

## Phase 1 – AWS infra and shared contracts ✅ (completed)

1. **S3 → SQS wiring for stream input** ✅
   - Add `stream_input/` notification on the existing input bucket, targeting the existing `video_worker` queue as described in `streaming-implementation-orchestration.md`, via the existing IaC stack (dev → staging → prod rollout).
   - Ensure the SQS queue policy permits S3 to send events for the new prefix, also managed via IaC.
2. **Output bucket permissions** ✅
   - Confirm/extend SageMaker (or inference) role permissions to allow `s3:PutObject` on `stream_output/*` (see orchestration doc), rolled out per environment. *(Confirmed: existing SageMaker role already allows output bucket; no change needed.)*
3. **`stream_sessions` table** ✅
   - Create DynamoDB `stream_sessions` with `session_id` PK and timestamps, as outlined in `streaming-implementation-orchestration.md` (required for production to support `#EXT-X-ENDLIST` and session expiry behavior).
4. **Shared parsing/types** ✅
   - Implement `StreamChunkPayload` and `parse_stream_chunk_key` for keys like `stream_input/{session_id}/chunk_{index:05d}.mp4` in a shared library, and treat this as a versioned contract (so future streaming variants can coexist).

---

## Phase 2 – Video-worker and job-worker changes ✅ (completed)

5. **Branch on key prefix in video-worker** ✅
   - In the S3 event handling, branch on `stream_input/` vs existing batch segment prefixes and construct the appropriate payload type (see orchestration plan).
   - Guard the streaming path behind a configuration flag so it can be enabled/disabled per environment and rolled out gradually.
6. **Implement `process_stream_chunk`** ✅
   - For stream payloads, invoke inference with `input_uri`, `output_uri`, and `mode`, writing to `stream_output/{session_id}/seg_{index:05d}.mp4` per `streaming-implementation-orchestration.md`.
   - Ensure `process_stream_chunk` is idempotent on `(session_id, index)` so duplicate S3 events or client retries are safe (overwriting the same output key is acceptable).
   - Do not write SegmentCompletions or trigger reassembly for streams.
   - Define a retry policy and maximum attempts for failed chunks, and decide what happens when a chunk permanently fails (e.g. log and skip the segment).
7. **SageMaker async backpressure integration** ✅
   - Extend the invocation store to mark stream vs batch entries.
   - In job-worker, skip SegmentCompletion/reassembly for stream entries while still cleaning up the invocation store (see orchestration doc details).
   - Implement per-session and global concurrency limits for streaming invocations so batch traffic is not starved. *(Deferred: v1 shares same semaphore; acceptable.)*
   - Define behavior when async inference queues are saturated (e.g. fail fast vs enqueue with bounded retries). *(Same as batch: semaphore blocks until slot free.)*

---

## Phase 3 – Web‑ui backend: sessions and playlist ✅ (completed)

8. **Session create API – `POST /stream_sessions`** ✅
   - Implement in `web-ui`, minting 1‑hour temporary credentials scoped to `stream_input/{session_id}/*` and returning `session_id`, `playlist_url`, and `upload` info, as specified in `streaming-implementation-client-capture.md` and `streaming-implementation-orchestration.md`.
   - Use STS/role assumption to mint credentials restricted to `s3:PutObject` (and `AbortMultipartUpload` if needed) on `stream_input/{session_id}/*` only (no read/list permissions).
9. **Session end API – `POST /stream_sessions/{id}/end`** ✅
   - Mark `ended_at` in `stream_sessions` to support `#EXT-X-ENDLIST` behavior.
   - Clarify behavior for late-arriving chunks after `ended_at` (e.g. still process but do not extend playlist duration, or log and ignore).
10. **Playlist API – `GET /stream/{session_id}/playlist.m3u8`** ✅
    - Implement according to `streaming-implementation-playback-hls.md`: list `stream_output/{session_id}/`, presign segment URLs, build EVENT playlist, and append `#EXT-X-ENDLIST` when `ended_at` is set.
    - Handle S3 eventual consistency by relying on the monotonic segment index model (e.g. `seg_{index:05d}.mp4`) and ensuring playlist generation is robust to slightly out-of-order visibility.
11. **Session expiry and cleanup** *(deferred)*
    - Implement automatic session expiry (e.g. background job that sets `ended_at` after N minutes of inactivity) so sessions that never explicitly call `/end` still terminate and can emit `#EXT-X-ENDLIST`.
    - Define how long to retain stream input/output objects and any related metadata, and where lifecycle rules are configured (IaC).

---

## Phase 4 – Desktop capture app

12. **Electron app skeleton**
    - Create `packages/stream-capture` (or equivalent) with Electron main/renderer split as described in `streaming-implementation-client-capture.md`.
13. **Session lifecycle integration**
    - On “Start streaming”, call `POST /stream_sessions` and store `session_id`, `playlist_url`, and temporary credentials.
    - On “Stop streaming”, call `POST /stream_sessions/{id}/end`.
14. **Capture, encode, and upload**
   - Implement source selection via `desktopCapturer`, 5 s chunking (initial target; tunable later based on end-to-end latency), MP4 (H.264 + AAC) encoding, and ordered uploads to `stream_input/{session_id}/chunk_{index:05d}.mp4` using temporary credentials, matching the client capture plan.
   - Implement per-chunk retry strategy for failed uploads (bounded retries with backoff) and define behavior when retries are exhausted (UI error, session stop, or degrade).
15. **UI/UX**
    - Single-window app with Start/Stop, current chunk index, and prominently displayed copyable `playlist_url` (per client capture doc).
   - Clearly surface error states (e.g. persistent upload failures) and recommend user actions.
16. **Packaging and distribution**
   - Decide on target platforms (e.g. Windows, macOS, Linux) and implement packaging for each.
   - Define how updates to the app will be distributed (auto-update vs manual download) and how versions map to backend changes.

---

## Phase 5 – Testing, observability, rollout, and docs

17. **End‑to‑end tests**
   - Manually or via scripts: create a session, upload a few chunks, verify segments in `stream_output/`, and open the playlist URL in PotPlayer/ffplay (see playback doc’s testing guidance).
   - Include multi-session tests to verify isolation (no cross-session leakage) and basic failure scenarios (missing chunk, failed inference, no `/end` call).
18. **Automated tests**
   - Unit tests for key parsing, stream vs batch branching, `process_stream_chunk` (including idempotency and error paths), and playlist generation (segment ordering and `#EXT-X-ENDLIST`).
   - Add integration tests around the playlist API and S3 listing behavior to ensure gaps or out-of-order segments are handled gracefully.
19. **Observability and alerting**
   - Add metrics for stream chunk processing (per-session counts, latencies, error rates), SQS queue depth, async inference in-flight counts, and playlist generation errors.
   - Ensure structured logs consistently include `session_id` and `index` across components.
   - Configure alerts for high error rates, growing queue depth, and sessions that do not emit `#EXT-X-ENDLIST` within an expected time window.
20. **Rollout and feature gating**
   - Gate streaming behind a feature flag or environment config, initially enabling only for internal/testing accounts.
   - Perform a small load test (multiple parallel sessions over a bounded period) before enabling for all users and monitor metrics closely during rollout.
21. **Documentation updates**
   - Keep `packages/stereo-spot-docs` in sync: add or update sections that describe the streaming capture app, orchestration path, HLS playback, and operational runbooks/troubleshooting, referencing the three root implementation docs and this tracking file.
   - Clearly document any non-goals for this phase (e.g. ultra-low latency, mobile capture, DRM) to avoid scope creep.

