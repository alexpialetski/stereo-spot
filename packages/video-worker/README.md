# Video worker

Consumes the **video-worker SQS queue** (raw S3 event notifications for segment uploads). Parses the segment key via **shared-types** `parse_segment_key`. Inference is **backend-switchable**: **`INFERENCE_BACKEND=stub`** (default) downloads segment, runs stub, uploads result; **`INFERENCE_BACKEND=sagemaker`** invokes a SageMaker endpoint with S3 URIs; **`INFERENCE_BACKEND=http`** POSTs to `INFERENCE_HTTP_URL/invocations` (same JSON body; for dev/testing with EC2). Writes **SegmentCompletion** to DynamoDB.

## Behaviour

1. **Receive message** — Long-poll the video-worker queue. Message body is the S3 event JSON (segment object created in input bucket).
2. **Parse** — Use **`parse_segment_key(bucket, key)`** from shared-types to get `VideoWorkerPayload` (job_id, segment_index, total_segments, segment_s3_uri, mode). Invalid or non-segment keys are skipped.
3. **Inference** — **Stub:** download segment, run `process_segment(bytes) -> bytes`, upload to **`jobs/{job_id}/segments/{segment_index}.mp4`**. **SageMaker:** call `InvokeEndpoint` with S3 URIs; endpoint writes result to that key. **HTTP:** POST to `INFERENCE_HTTP_URL/invocations` with same JSON (for EC2/dev).
4. **Record** — Put **SegmentCompletion** (job_id, segment_index, output_s3_uri, completed_at, total_segments) to SegmentCompletionStore (DynamoDB).
5. **Delete message** — Delete the SQS message on success.

All segment key parsing uses **shared-types** only; no duplicate logic. Output key format is defined in this package (`build_output_segment_key`).


## Environment variables

| Env var | Description |
|---------|-------------|
| `INPUT_BUCKET_NAME` | S3 input bucket (segments live here) |
| `OUTPUT_BUCKET_NAME` | S3 output bucket (segment outputs, final.mp4) |
| `SEGMENT_COMPLETIONS_TABLE_NAME` | DynamoDB SegmentCompletions table |
| `VIDEO_WORKER_QUEUE_URL` | SQS video-worker queue URL |
| `INFERENCE_BACKEND` | `stub` (default), `sagemaker`, or `http` |
| `SAGEMAKER_ENDPOINT_NAME` | Required when `INFERENCE_BACKEND=sagemaker`; SageMaker endpoint name |
| `SAGEMAKER_REGION` | (Optional) AWS region for the endpoint; defaults to task region |
| `INFERENCE_HTTP_URL` | Required when `INFERENCE_BACKEND=http`; base URL of inference server (e.g. http://10.0.1.5:8080) |
| `AWS_REGION` | (Optional) AWS region |
| `AWS_ENDPOINT_URL` | (Optional) e.g. LocalStack |

**Segment size and timeout:** When using SageMaker, segment processing time is dominated by the endpoint. Set the video-worker SQS **visibility timeout** to at least 2–3× the expected end-to-end time (e.g. 15–20 minutes for ~5 min segments).

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
