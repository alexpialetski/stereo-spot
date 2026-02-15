# Media worker

Single package and Docker image that handles **chunking** and **reassembly** (both use ffmpeg). Consumes two SQS queues in one process (two threads): the **chunking queue** (S3 event when user uploads source) and the **reassembly queue** (job_id when all segments are done). Saves storage by shipping one ~600MB image instead of two.

## Behaviour

### Chunking (chunking queue)

1. **Receive message** — Long-poll the chunking queue (S3 event: bucket, key).
2. **Parse** — Use `parse_input_key(key)` from **shared-types** to get `job_id` (key must be `input/{job_id}/source.mp4`).
3. **Load job** — Get the job from **JobStore**; if not found or already past chunking, skip.
4. **Update status** — Set job to `chunking_in_progress`.
5. **Download** — Download the source from S3 to a temp file.
6. **Chunk** — Run ffmpeg segment (keyframe-aligned, ~5 min per segment): `-f segment -segment_time 300 -c copy`.
7. **Upload segments** — Build keys with **`build_segment_key(job_id, segment_index, total_segments, mode)`** and upload to the input bucket.
8. **Complete** — JobStore.update with `status=chunking_complete` and `total_segments`.
9. **Delete message** — Delete the SQS message on success.

### Reassembly (reassembly queue)

1. **Receive** message (body: `{"job_id": "..."}`).
2. **Lock** — Conditional update on **ReassemblyTriggered**; if failed, delete message (idempotent).
3. **Load job**; if already `completed`, delete message and exit.
4. **Idempotency** — If `jobs/{job_id}/final.mp4` already exists, update Job to `completed` and delete message.
5. **Segment list** — Query **SegmentCompletions** by `job_id` (ordered by `segment_index`).
6. **Download** each segment to a temp dir.
7. **Concat** — ffmpeg concat demuxer (`-f concat -c copy`).
8. **Upload** to `jobs/{job_id}/final.mp4` (multipart for large files).
9. **Update Job** to `status=completed`, `completed_at`.
10. **Delete** message.

## Environment variables

Required (from Terraform / `terraform-outputs.env`):

| Env var | Description |
|---------|-------------|
| `INPUT_BUCKET_NAME` | S3 input bucket (source + segments) |
| `OUTPUT_BUCKET_NAME` | S3 output bucket (segment outputs + final.mp4) |
| `JOBS_TABLE_NAME` | DynamoDB Jobs table |
| `SEGMENT_COMPLETIONS_TABLE_NAME` | DynamoDB SegmentCompletions table |
| `REASSEMBLY_TRIGGERED_TABLE_NAME` | DynamoDB ReassemblyTriggered table (lock) |
| `CHUNKING_QUEUE_URL` | SQS chunking queue URL |
| `REASSEMBLY_QUEUE_URL` | SQS reassembly queue URL |

Optional:

- `AWS_REGION` (default: us-east-1)
- `AWS_ENDPOINT_URL` (e.g. LocalStack)
- `CHUNK_SEGMENT_DURATION_SEC` (default 300)

## Local run

From the monorepo root:

```bash
# Set env vars (e.g. source packages/aws-infra/terraform-outputs.env)
export INPUT_BUCKET_NAME=...
export OUTPUT_BUCKET_NAME=...
export JOBS_TABLE_NAME=...
export SEGMENT_COMPLETIONS_TABLE_NAME=...
export REASSEMBLY_TRIGGERED_TABLE_NAME=...
export CHUNKING_QUEUE_URL=...
export REASSEMBLY_QUEUE_URL=...

pip install -e packages/shared-types -e packages/aws-adapters -e packages/media-worker
python -m media_worker.main
```

The process runs two threads (chunking loop and reassembly loop) until interrupted.

## Docker build

Build from the **repository root**:

```bash
docker build -f packages/media-worker/Dockerfile -t stereo-spot-media-worker:latest .
```

Or via Nx:

```bash
nx run media-worker:build
```

The image includes **ffmpeg** and the Python runtime. Set the same env vars at runtime (e.g. via ECS task definition).

## Tests and lint

```bash
nx run media-worker:test
nx run media-worker:lint
```

Tests cover: S3 event parsing, segment key generation, chunking flow (mocked), reassembly flow (lock, idempotency, concat), and output key building.
