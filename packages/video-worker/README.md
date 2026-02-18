# Video worker

Consumes **two SQS queues**: (1) **video-worker queue** — S3 events when segments are uploaded to the input bucket; (2) **segment-output queue** — S3 events when the inference side writes a segment to the output bucket. Acts as coordinator: invokes inference (SageMaker async, HTTP, or stub); SegmentCompletion is written when the output-bucket S3 event is received, not by polling for the file.

**Module layout:** Logic is split by responsibility. **`inference`** — inference-queue consumer: parse S3 event, run model (SageMaker/HTTP/stub), delete message on success. **`segment_output`** — segment-output-queue consumer: parse output-bucket S3 event, put SegmentCompletion, optionally trigger reassembly, delete message. **`reassembly_trigger`** — when all segments are complete for a chunking_complete job, conditionally create ReassemblyTriggered and send job_id to the reassembly queue. **`main`** wires env and runs both loops in two threads.

## Behaviour

**Inference path (video-worker queue):**

1. **Receive message** — Long-poll the video-worker queue. Message body is the S3 event JSON (segment object created in input bucket).
2. **Parse** — Use **`parse_segment_key(bucket, key)`** from shared-types to get `VideoWorkerPayload`.
3. **Inference** — **SageMaker:** InvokeEndpointAsync with S3 URIs; poll only for the async response (success/error). On success delete message (SegmentCompletion is written by the segment-output consumer when the file appears). On error do not delete (retry). **HTTP:** POST to `INFERENCE_HTTP_URL/invocations`; then put SegmentCompletion and delete. **Stub:** download, run stub, upload, put SegmentCompletion, delete.
4. **Delete message** — Delete on success (SageMaker: after async success; stub/HTTP: after upload and SegmentCompletion put).

**Segment-output path (segment-output queue):**

1. **Receive message** — Long-poll the segment-output queue. Message body is the S3 event JSON (object created in output bucket, prefix `jobs/`, suffix `.mp4`).
2. **Parse** — Use **`parse_output_segment_key(bucket, key)`** from shared-types. Keys like `jobs/{job_id}/final.mp4` are skipped (return None).
3. **Record** — Put **SegmentCompletion** (job_id, segment_index, output_s3_uri, completed_at, total_segments=None) to DynamoDB.
4. **Reassembly trigger (trigger-on-write)** — After each SegmentCompletion put, the video-worker checks whether the job has `status: chunking_complete` and `count(SegmentCompletions) == total_segments`. When so, it performs a conditional create on **ReassemblyTriggered** and, on success, sends `job_id` to the reassembly queue. Media-worker then consumes the reassembly queue and runs ffmpeg concat.
5. **Delete message** — Delete on success.

All key parsing uses **shared-types** only. The video-worker runs both loops in two threads.


## Environment variables

| Env var | Description |
|---------|-------------|
| `INPUT_BUCKET_NAME` | S3 input bucket (segments live here) |
| `OUTPUT_BUCKET_NAME` | S3 output bucket (segment outputs, final.mp4) |
| `SEGMENT_COMPLETIONS_TABLE_NAME` | DynamoDB SegmentCompletions table |
| `VIDEO_WORKER_QUEUE_URL` | SQS video-worker queue URL (inference requests) |
| `SEGMENT_OUTPUT_QUEUE_URL` | SQS segment-output queue URL (output bucket S3 events) |
| `REASSEMBLY_TRIGGERED_TABLE_NAME` | DynamoDB ReassemblyTriggered table (conditional create when last segment completes) |
| `REASSEMBLY_QUEUE_URL` | SQS reassembly queue URL (video-worker sends job_id when last segment completes) |
| `INFERENCE_BACKEND` | `stub` (default), `sagemaker`, or `http` |
| `SAGEMAKER_ENDPOINT_NAME` | Required when `INFERENCE_BACKEND=sagemaker`; SageMaker endpoint name |
| `SAGEMAKER_REGION` | (Optional) AWS region for the endpoint; defaults to task region |
| `SAGEMAKER_INVOKE_TIMEOUT_SECONDS` | (Optional) Async invocation timeout and poll timeout (seconds); default **1200** (20 min). |
| `SAGEMAKER_ASYNC_POLL_INTERVAL_SECONDS` | (Optional) Seconds between S3 polls for async response; default **15**. |
| `INFERENCE_HTTP_URL` | Required when `INFERENCE_BACKEND=http`; base URL of inference server (e.g. http://10.0.1.5:8080) |
| `AWS_REGION` | (Optional) AWS region |
| `AWS_ENDPOINT_URL` | (Optional) e.g. LocalStack |

**Segment size and timeout:** Inference uses **SageMaker Asynchronous Inference** (InvokeEndpointAsync). The worker invokes async then polls only for the small async response (success/error), not for the segment file. Segment completion is event-driven from the output bucket. The video-worker queue **visibility timeout** can be lower than full inference time (e.g. 10 minutes) since the worker does not hold the message for the full run.

## Local run

From the monorepo root:

```bash
export INPUT_BUCKET_NAME=...
export OUTPUT_BUCKET_NAME=...
export SEGMENT_COMPLETIONS_TABLE_NAME=...
export VIDEO_WORKER_QUEUE_URL=...
export SEGMENT_OUTPUT_QUEUE_URL=...
export REASSEMBLY_TRIGGERED_TABLE_NAME=...
export REASSEMBLY_QUEUE_URL=...

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
