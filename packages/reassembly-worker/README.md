# reassembly-worker

CPU-only worker that consumes the **reassembly queue** (one message per job: `job_id`), concatenates segment outputs with ffmpeg, uploads `final.mp4` to the output bucket, and updates the Job to `status=completed`.

## Flow

1. **Receive** message from reassembly queue (body: `{"job_id": "..."}`).
2. **Lock:** Conditional update on **ReassemblyTriggered** (set `reassembly_started_at` only if the item exists and that attribute is absent). If the update fails, another worker has the lock → delete message and exit (idempotent).
3. **Load job** from JobStore; if already `completed`, delete message and exit.
4. **Idempotency:** If `jobs/{job_id}/final.mp4` already exists in the output bucket, update Job to `completed` and delete message.
5. **Segment list:** Query **SegmentCompletions** by `job_id` (ordered by `segment_index`). No S3 list — DynamoDB is the source of truth.
6. **Download** each segment (using `output_s3_uri` from completions) to a temp dir.
7. **Concat:** Run ffmpeg concat demuxer (`-f concat -c copy`) to produce one file.
8. **Upload** to `jobs/{job_id}/final.mp4` (uses multipart for large files).
9. **Update Job** to `status=completed`, `completed_at`.
10. **Delete** message.

## Lock semantics

- The **reassembly trigger Lambda** does a **conditional create** on ReassemblyTriggered (item must not exist) when the last segment completes; on success it sends `job_id` to the reassembly queue.
- The **reassembly-worker** does a **conditional update** (set `reassembly_started_at` only if the item exists and that attribute is absent). Only one worker wins; others delete the message so it does not reappear.

## Env vars

Required (from Terraform / `terraform-outputs.env`):

- `INPUT_BUCKET_NAME`
- `OUTPUT_BUCKET_NAME`
- `JOBS_TABLE_NAME`
- `SEGMENT_COMPLETIONS_TABLE_NAME`
- `REASSEMBLY_TRIGGERED_TABLE_NAME`
- `REASSEMBLY_QUEUE_URL`

Optional:

- `AWS_REGION` (default: us-east-1)
- `AWS_ENDPOINT_URL` (e.g. LocalStack)

## Local run

```bash
# From repo root, with env set (e.g. source packages/aws-infra/terraform-outputs.env)
pip install -e packages/shared-types -e packages/aws-adapters -e packages/reassembly-worker
python -m reassembly_worker.main
```

## Docker

From repo root:

```bash
docker build -f packages/reassembly-worker/Dockerfile -t stereo-spot-reassembly-worker:latest .
```

## Tests

```bash
nx run reassembly-worker:test
```

Or from the package:

```bash
pip install -e ../shared-types -e ../aws-adapters -e . && pytest -v
```
