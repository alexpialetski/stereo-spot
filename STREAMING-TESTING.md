# Streaming – how to test from scratch

Use this guide to verify the streaming feature end-to-end when you already have **infra running** (Terraform applied: S3 buckets, SQS queues, DynamoDB tables including `stream_sessions`, optional ECS services).

Reference: [streaming-implementation-plan.md](./streaming-implementation-plan.md).

---

## 1. Prerequisites

**Infra (you have this):**

- Terraform applied: input bucket, output bucket, `video_worker` SQS queue, **stream_sessions** DynamoDB table.
- S3 event: `stream_input/*.mp4` → `video_worker` queue (see `packages/aws-infra/s3_events.tf`).
- Web-ui and video-worker ECS tasks have the right env (or you run them locally with `.env`).

**For local testing:**

- `packages/aws-infra/.env` (or your env file) must include at least:
  - `INPUT_BUCKET_NAME`
  - `OUTPUT_BUCKET_NAME`
  - `AWS_REGION` (or `REGION`)
  - **`STREAM_SESSIONS_TABLE_NAME`** — required for session create/end and playlist; if missing, add it (e.g. from Terraform: `nx run aws-infra:terraform-output` and add `STREAM_SESSIONS_TABLE_NAME=<name>` to `.env`; table name is usually `stereo-spot-stream-sessions`).
  - **`STREAM_UPLOAD_ROLE_ARN`** — required when using **session credentials** (SSO, assumed role); otherwise POST /stream_sessions fails with "Cannot call GetFederationToken with session credentials". Run `nx run aws-infra:terraform-output` after apply to get this in `.env`.

**For full pipeline (chunks → segments → playlist):**

- Video-worker must have **`STREAMING_ENABLED=true`** (ECS task env or local env). Default is `false`; without it, stream messages are dropped.

---

## 2. Checks before you start

Run these once to confirm infra and config.

| Check | How | Expected |
|-------|-----|----------|
| Stream sessions table exists | `aws dynamodb describe-table --table-name <STREAM_SESSIONS_TABLE_NAME>` (use name from `.env` or Terraform output) | Table description, no error |
| S3 event for stream_input | AWS Console → S3 → input bucket → Properties → Event notifications; or `aws s3api get-bucket-notification-configuration --bucket <INPUT_BUCKET_NAME>` | Notification with prefix `stream_input/` and target = video_worker queue |
| Video-worker queue | `aws sqs get-queue-attributes --queue-url $VIDEO_WORKER_QUEUE_URL --attribute-names All` (from `.env`) | Queue exists |
| Web-ui env for streaming | Ensure web-ui process has `INPUT_BUCKET_NAME`, `OUTPUT_BUCKET_NAME`, `STREAM_SESSIONS_TABLE_NAME` (and AWS creds for STS + DynamoDB) | No missing-env errors at startup |

---

## 3. Option A: Test against deployed web-ui (ECS)

If web-ui and video-worker are running on ECS:

1. **Base URL:** Use your web-ui URL (e.g. `https://<WEB_UI_ALB_DNS_NAME>` or the value of `WEB_UI_URL` from Terraform / `.env`).

2. **Run the API smoke script:**
   ```bash
   python scripts/stream_e2e.py --base-url https://<your-web-ui-host>
   ```
   - **Check:** Exit code 0 and output like: `Created session_id=...`, `Playlist OK`, `Playlist after end includes #EXT-X-ENDLIST`.
   - If **404 on playlist:** Session store not configured or table name wrong (see Prerequisites).
   - If **connection error:** Wrong URL or ALB/security group.

3. **Full flow with desktop app:** Build and run stream-capture, set API base to your web-ui URL, then follow [Section 5](#5-full-flow-with-stream-capture-app) (playlist URL will be your host + `/stream/<session_id>/playlist.m3u8`).

---

## 4. Option B: Test with web-ui (and optionally video-worker) locally

Use this to test session API, playlist, and (if you run video-worker locally) the full chunk → segment path.

### 4.1 Start web-ui locally

From repo root, with `packages/aws-infra/.env` containing at least `INPUT_BUCKET_NAME`, `OUTPUT_BUCKET_NAME`, `STREAM_SESSIONS_TABLE_NAME`, `AWS_REGION` (and AWS credentials in env or default profile):

```bash
nx run web-ui:serve
```

Or:

```bash
export STEREOSPOT_ENV_FILE="${PWD}/packages/aws-infra/.env"
cd packages/web-ui && uvicorn stereo_spot_web_ui.main:app --reload
```

- **Check:** Server starts; no errors about missing `STREAM_SESSIONS_TABLE_NAME` or buckets. If create session works but playlist returns 404, add `STREAM_SESSIONS_TABLE_NAME` to `.env` (DynamoDB table must exist).

### 4.2 Run API smoke test

In another terminal:

```bash
python scripts/stream_e2e.py --base-url http://localhost:8000
```

- **Check:** Exit code 0. You should see:
  - `Created session_id=<uuid>`
  - `Playlist URL: http://localhost:8000/stream/<session_id>/playlist.m3u8`
  - `Playlist OK (EVENT type)`
  - `Playlist after end includes #EXT-X-ENDLIST` (if store is configured)

### 4.3 Create session and inspect playlist (manual)

```bash
# Create session
curl -s -X POST http://localhost:8000/stream_sessions -H "Content-Type: application/json" -d '{"mode":"sbs"}' | jq .

# Save session_id and playlist_url from the response, then:
SESSION_ID=<paste-session-id-here>

# Get playlist (may have 0 segments at first)
curl -s "http://localhost:8000/stream/${SESSION_ID}/playlist.m3u8"

# End session
curl -s -X POST "http://localhost:8000/stream_sessions/${SESSION_ID}/end" -w "%{http_code}"

# Get playlist again (should include #EXT-X-ENDLIST)
curl -s "http://localhost:8000/stream/${SESSION_ID}/playlist.m3u8"
```

- **Checks:**
  - Create returns 200 with `session_id`, `playlist_url`, `upload` (access_key_id, secret_access_key, session_token, bucket, region, expires_at).
  - First playlist: 200, body contains `#EXTM3U`, `#EXT-X-PLAYLIST-TYPE:EVENT`; may have no segments yet.
  - End returns 204.
  - Second playlist: 200, body contains `#EXT-X-ENDLIST`.

### 4.4 (Optional) Upload a test chunk and run video-worker

To see segments in the playlist you need:

1. Upload at least one object to `stream_input/<session_id>/chunk_00000.mp4` (must be a valid MP4; the video-worker will run inference and write to `stream_output/<session_id>/seg_00000.mp4`).
2. Video-worker running with **STREAMING_ENABLED=true**, consuming the same queue.

**Upload using temp credentials from create response:**

- Use the `upload` object from the create-session response (access_key_id, secret_access_key, session_token, bucket, region).
- Example with AWS CLI (after exporting or configuring those credentials):

  ```bash
  # Create a tiny test MP4 (or use any small valid MP4)
  # Then upload (replace BUCKET, SESSION_ID, and use the temp creds):
  aws s3 cp /path/to/small.mp4 s3://<BUCKET>/stream_input/<SESSION_ID>/chunk_00000.mp4
  ```

- **Check:** After a few seconds, object appears under `stream_output/<SESSION_ID>/seg_00000.mp4` (if video-worker is running with STREAMING_ENABLED=true and inference backend is working). Then GET playlist again — it should list that segment with a presigned URL.

**Run video-worker locally (stub or HTTP inference):**

- Set in env: `VIDEO_WORKER_QUEUE_URL`, `INPUT_BUCKET_NAME`, `OUTPUT_BUCKET_NAME`, `STREAMING_ENABLED=true`, and either stub (`INFERENCE_BACKEND=stub`) or HTTP inference URL.
- Run the video-worker so it receives the S3 event from the queue and processes the stream chunk.
- **Check:** Logs show `session_id=... chunk_index=...` and output object in `stream_output/`.

---

## 5. Full flow with stream-capture app

This tests: create session from the app → capture → upload chunks → playlist URL → end session.

1. **Web-ui running** (local or deployed) and reachable from the machine where you run the app.

2. **Build and start stream-capture:**
   ```bash
   nx run stream-capture:build
   nx run stream-capture:start
   ```
   If web-ui is not on localhost:8000, set env before start:
   ```bash
   export STREAM_CAPTURE_API_BASE=http://localhost:8000   # or your web-ui URL
   nx run stream-capture:start
   ```

3. **In the app:**
   - Choose a capture source (e.g. a window or screen).
   - Click **Start streaming**.
   - **Check:** No error; UI shows "Streaming… chunk 0" and a **playlist URL** (e.g. `http://localhost:8000/stream/<session_id>/playlist.m3u8`).
   - Copy the playlist URL.

4. **Playback (optional):** Open the playlist URL in an HLS player that supports 3D SBS (e.g. PotPlayer). After the first 5 s chunk is uploaded and processed, you should see the first segment (and more as chunks are produced).

5. **Stop and end:**
   - Click **Stop capture** (stops recording; session still active).
   - Click **End session** (marks session ended; playlist will include `#EXT-X-ENDLIST`).
   - **Check:** GET the playlist URL again; response should contain `#EXT-X-ENDLIST`.

**Checks summary:**

| Step | What to check |
|------|----------------|
| Start streaming | Session created; playlist URL shown; no "create failed" error |
| While streaming | Chunk index increments; no persistent upload errors |
| Playlist in player | After video-worker processes chunks, segments play (if inference is running) |
| End session | Playlist URL still works and includes `#EXT-X-ENDLIST` |

---

## 6. Troubleshooting quick reference

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| POST /stream_sessions 500 or STS error | Missing/invalid AWS creds or input bucket name | Check web-ui env: AWS credentials, INPUT_BUCKET_NAME |
| GET playlist 404 | Session not in store | Set STREAM_SESSIONS_TABLE_NAME; ensure table exists; create session again |
| Playlist empty (no #EXTINF) | No segments in stream_output/ | Ensure video-worker has STREAMING_ENABLED=true; upload chunks to stream_input/; check S3 event for stream_input/ → video_worker queue |
| Stream-capture "create failed" | Web-ui unreachable or API error | Check STREAM_CAPTURE_API_BASE; run stream_e2e.py against same URL |
| Video-worker not processing stream chunks | STREAMING_ENABLED false or message not in queue | Set STREAMING_ENABLED=true; confirm S3 notification for stream_input/ targets video_worker queue |

More detail: [packages/stereo-spot-docs/docs/aws/runbooks.md](packages/stereo-spot-docs/docs/aws/runbooks.md) §10 Streaming.
