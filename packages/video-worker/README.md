# Video worker

Consumes the **video-worker SQS queue** (raw S3 event notifications for segment uploads). Parses the segment key via **shared-types** `parse_segment_key`, downloads the segment from the input bucket, runs **inference** (stub: copy pass-through for now; StereoCrafter or other model later), uploads the result to the output bucket at `jobs/{job_id}/segments/{segment_index}.mp4`, and writes a **SegmentCompletion** to DynamoDB.

## Behaviour

1. **Receive message** — Long-poll the video-worker queue. Message body is the S3 event JSON (segment object created in input bucket).
2. **Parse** — Use **`parse_segment_key(bucket, key)`** from shared-types to get `VideoWorkerPayload` (job_id, segment_index, total_segments, segment_s3_uri, mode). Invalid or non-segment keys are skipped.
3. **Download** — Download segment bytes from the segment S3 URI (input bucket).
4. **Inference** — Run the configured model. **Stub:** `process_segment(bytes) -> bytes` returns input unchanged (no GPU). Replace with a real model (e.g. StereoCrafter) by swapping the implementation (env-driven or plugin).
5. **Upload** — Upload result to output bucket at **`jobs/{job_id}/segments/{segment_index}.mp4`**.
6. **Record** — Put **SegmentCompletion** (job_id, segment_index, output_s3_uri, completed_at, total_segments) to SegmentCompletionStore (DynamoDB). Reassembly trigger and media-worker use this.
7. **Delete message** — Delete the SQS message on success.

All segment key parsing uses **shared-types** only; no duplicate logic. Output key format is defined in this package (`build_output_segment_key`).

## Model swapping (later)

The stub allows the pipeline to run without GPU. To add StereoCrafter or another model:

- Replace or wrap `process_segment` (e.g. in a small `model_` module) with an implementation that decodes video, runs inference, encodes output.
- Use env (e.g. `MODEL=stereocrafter`) or a factory to choose the implementation at startup.
- Keep the runner and queue logic unchanged; only the “process bytes → bytes” step is swappable.

## Environment variables

Same as **aws-adapters** when using env-based wiring:

| Env var | Description |
|---------|-------------|
| `INPUT_BUCKET_NAME` | S3 input bucket (segments live here) |
| `OUTPUT_BUCKET_NAME` | S3 output bucket (segment outputs, final.mp4) |
| `SEGMENT_COMPLETIONS_TABLE_NAME` | DynamoDB SegmentCompletions table |
| `VIDEO_WORKER_QUEUE_URL` | SQS video-worker queue URL |
| `AWS_REGION` | (Optional) AWS region |
| `AWS_ENDPOINT_URL` | (Optional) e.g. LocalStack |

## Local run

From the monorepo root:

```bash
export INPUT_BUCKET_NAME=...
export OUTPUT_BUCKET_NAME=...
export SEGMENT_COMPLETIONS_TABLE_NAME=...
export VIDEO_WORKER_QUEUE_URL=...

pip install -e packages/shared-types -e packages/aws-adapters -e packages/video-worker
python -m video_worker.main
```

## Docker build

Build from the **repository root** (so the Dockerfile can copy `packages/shared-types` and `packages/aws-adapters`):

```bash
docker build -f packages/video-worker/Dockerfile -t stereo-spot-video-worker:latest .
```

Or via Nx:

```bash
nx run video-worker:build
```

The image has no system deps (unlike chunking-worker’s ffmpeg); set the same env vars at runtime (e.g. via ECS or `docker run -e ...`).

## Tests and lint

```bash
nx run video-worker:test
nx run video-worker:lint
```

Tests cover: S3 event body → segment key parsing (shared-types), output key generation, stub model pass-through, and one full pipeline run with mocked ObjectStorage and SegmentCompletionStore.
