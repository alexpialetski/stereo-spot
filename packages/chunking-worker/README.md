# Chunking worker

Consumes the **chunking SQS queue** (raw S3 event notifications), downloads the source video from S3, splits it into keyframe-aligned segments with **ffmpeg**, uploads each segment to the input bucket using the **canonical segment key** from `shared-types`, and updates the Job in DynamoDB to `chunking_complete` with `total_segments`.

## Behaviour

1. **Receive message** — Long-poll the chunking queue for one message. The message body is the S3 event notification JSON (`Records[0].s3.bucket.name`, `Records[0].s3.object.key`).
2. **Parse** — Use `parse_input_key(key)` from **shared-types** to get `job_id` (key must be `input/{job_id}/source.mp4`). Invalid or non-input keys are skipped.
3. **Load job** — Get the job from **JobStore** (DynamoDB). If not found or already past chunking, skip.
4. **Update status** — Set job to `chunking_in_progress` so recovery tools can find stuck jobs.
5. **Download** — Download the source object from S3 to a temp file via **ObjectStorage**.
6. **Chunk** — Run ffmpeg segment (keyframe-aligned, ~5 min per segment by default): `-f segment -segment_time 300 -c copy`.
7. **Upload segments** — For each segment file, build the key with **`build_segment_key(job_id, segment_index, total_segments, mode)`** from shared-types and upload to the **input bucket**. Segment uploads will trigger S3 event notifications to the video-worker queue (Step 4.2).
8. **Complete** — Single **JobStore.update** with `status=chunking_complete` and `total_segments`.
9. **Delete message** — Delete the SQS message on success.

All key parsing and key building use **shared-types** only; no duplicate logic.

## Environment variables

Same as **aws-adapters** when using env-based wiring (see `packages/aws-adapters/README.md`):

| Env var | Description |
|---------|-------------|
| `INPUT_BUCKET_NAME` | S3 input bucket (source + segments) |
| `JOBS_TABLE_NAME` | DynamoDB Jobs table |
| `CHUNKING_QUEUE_URL` | SQS chunking queue URL |
| `AWS_REGION` | (Optional) AWS region |
| `AWS_ENDPOINT_URL` | (Optional) e.g. LocalStack |
| `CHUNK_SEGMENT_DURATION_SEC` | (Optional) Segment duration in seconds (default 300) |

## Local run

From the monorepo root:

```bash
# Set env vars (e.g. from terraform-outputs.env or export manually)
export INPUT_BUCKET_NAME=...
export JOBS_TABLE_NAME=...
export CHUNKING_QUEUE_URL=...

pip install -e packages/shared-types -e packages/aws-adapters -e packages/chunking-worker
python -m chunking_worker.main
```

The worker runs until interrupted. It receives one message at a time and processes it (download → ffmpeg → upload segments → update job → delete message).

## Docker build

Build from the **repository root** so the Dockerfile can copy `packages/shared-types` and `packages/aws-adapters`:

```bash
docker build -f packages/chunking-worker/Dockerfile -t stereo-spot-chunking-worker:latest .
```

Or via Nx:

```bash
nx run chunking-worker:build
```

The image includes **ffmpeg** and the Python runtime. At runtime, set the same env vars (e.g. via EKS deployment or `docker run -e ...`).

## Tests and lint

```bash
nx run chunking-worker:test
nx run chunking-worker:lint
```

Tests cover: S3 event body parsing and input key validation, segment key generation (shared-types), and one full chunking flow with mocked **JobStore** and **ObjectStorage** (ffmpeg is mocked so no real video file is required).
