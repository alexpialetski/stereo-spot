# reassembly-trigger (Lambda)

Python Lambda invoked by **DynamoDB Streams** on the SegmentCompletions table. When a new segment completion is written, the stream delivers a batch of records. For each distinct `job_id` in the batch, the Lambda:

1. Gets the **Job** (DynamoDB Jobs table) and checks `status == chunking_complete` and `total_segments` is set.
2. **Counts** SegmentCompletions for that `job_id` (Query by PK).
3. If `count == total_segments`, performs a **conditional create** on **ReassemblyTriggered** (`attribute_not_exists(job_id)`). Only if the put succeeds (idempotent: first writer wins), it sends `job_id` to the **reassembly SQS queue** (body: `{"job_id": "..."}`).

This triggers the media-worker (reassembly) to run once per job when the last segment completes.

## Event shape (DynamoDB Stream)

Each record in `event["Records"]` has:

- `eventName`: e.g. `INSERT`, `MODIFY`
- `dynamodb.Keys`: `job_id` (S), `segment_index` (N)
- `dynamodb.NewImage`: full item after the change

The handler extracts distinct `job_id` values from the batch and processes each (get Job, count completions, conditional create, send to SQS).

## Shared-types from wheel

The Lambda deployment package is built so that **shared-types** comes from the **built wheel** (same artifact as other consumers), not from source or `pip install -e`:

1. **Nx:** `reassembly-trigger:build` depends on `shared-types:build`. Run `nx run shared-types:build` first (or let the build do it).
2. **Build script** (`scripts/build_deploy_zip.sh`): installs the wheel from `../shared-types/dist/stereo_spot_shared-*.whl` into a staging dir with `pip install --no-deps <wheel> -t <staging>`, then copies `reassembly_trigger/` into staging and zips. Result: `dist/deploy.zip`.
3. **Terraform** uses that zip (`packages/reassembly-trigger/dist/deploy.zip` by default) for the Lambda function.

This keeps the Lambda in sync with the same shared-types version as workers and web-ui.

## Env vars (set by Terraform)

- `JOBS_TABLE_NAME`
- `SEGMENT_COMPLETIONS_TABLE_NAME`
- `REASSEMBLY_TRIGGERED_TABLE_NAME`
- `REASSEMBLY_QUEUE_URL`

## Terraform deploy

1. Build the zip: `nx run reassembly-trigger:build`
2. Apply infra (from `packages/aws-infra` or via Nx): `terraform apply`. The Lambda and its event source mapping (SegmentCompletions stream → Lambda) are created. If the zip is missing, the Lambda and event source mapping are skipped (count = 0); run the build and apply again.

Optional: override the zip path with `-var="lambda_reassembly_trigger_zip_path=/path/to/deploy.zip"`.

## Tests

```bash
nx run reassembly-trigger:test
```

Or: `pip install -e ../shared-types -e . && pytest -v` from the package directory.
