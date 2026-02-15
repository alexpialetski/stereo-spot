# Stereo-Spot Web UI

FastAPI server-rendered UI for the stereo-spot pipeline: dashboard, job creation, upload URL, list completed jobs, and presigned playback.

## Purpose

- **Dashboard** (`GET /`): Welcome and form to create a new job (select mode: anaglyph or SBS).
- **Create job** (`POST /jobs`): Creates a job in DynamoDB (status `created`), generates a presigned PUT URL for `input/{job_id}/source.mp4`, and redirects to the job detail page.
- **Job detail** (`GET /jobs/{job_id}`): Shows upload URL and instructions when status is `created`; shows status and play link when completed.
- **List completed jobs** (`GET /jobs`): Queries DynamoDB GSI `status-completed_at` with `status=completed`, descending by `completed_at`, with pagination.
- **Play** (`GET /jobs/{job_id}/play`): Redirects to a presigned GET URL for `jobs/{job_id}/final.mp4` in the output bucket.

Presigned URLs use the keys defined in [ARCHITECTURE.md](../../ARCHITECTURE.md): `input/{job_id}/source.mp4` (upload) and `jobs/{job_id}/final.mp4` (playback).

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard |
| GET | `/jobs` | List completed jobs (HTML) |
| POST | `/jobs` | Create job (form: `mode`), redirect to job detail |
| GET | `/jobs/{job_id}` | Job detail / upload page |
| GET | `/jobs/{job_id}/play` | Redirect to presigned playback URL |

## Dependencies

- **shared-types**: Job, JobStore, ObjectStorage, StereoMode, JobStatus, etc.
- **aws-adapters**: AWS implementations of JobStore and ObjectStorage (DynamoDB, S3). Used when running against real AWS or LocalStack.

The app uses the **JobStore** and **ObjectStorage** abstractions; implementations are injected via `app.state` (tests) or built from environment variables (production).

## Environment variables

When not using mocks (e.g. on ECS or local against AWS), set the same variables as for other packages that use aws-adapters:

- `INPUT_BUCKET_NAME` — input S3 bucket
- `OUTPUT_BUCKET_NAME` — output S3 bucket
- `JOBS_TABLE_NAME` — DynamoDB Jobs table
- `AWS_REGION` (optional)
- `AWS_ENDPOINT_URL` (optional, e.g. LocalStack)

See [packages/aws-adapters/README.md](../aws-adapters/README.md) for the full list. On **ECS**, tasks use an **IAM task role**; no long-lived credentials are required.

## Local run

```bash
# From repo root: install dependencies and run
pip install -e packages/shared-types -e packages/aws-adapters -e packages/web-ui
# Set env vars (or use terraform-outputs.env from aws-infra)
export INPUT_BUCKET_NAME=...
export OUTPUT_BUCKET_NAME=...
export JOBS_TABLE_NAME=...
uvicorn stereo_spot_web_ui.main:app --reload
```

Or via Nx:

```bash
nx run web-ui:serve
```

(Ensure the required env vars are set before starting.)

## Tests

```bash
nx run web-ui:test
```

Unit tests use mocked JobStore and ObjectStorage (set on `app.state`) so no AWS or env vars are needed.

## Lint

```bash
nx run web-ui:lint
```
