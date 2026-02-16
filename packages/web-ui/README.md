# Stereo-Spot Web UI

FastAPI server-rendered UI for the stereo-spot pipeline: dashboard, job creation, upload URL, unified jobs list (in-progress + completed), embedded video player with download, and live progress via SSE.

## Purpose

- **Dashboard** (`GET /`): Welcome and form to create a new job (select mode: anaglyph or SBS).
- **Create job** (`POST /jobs`): Creates a job in DynamoDB (status `created`), generates a presigned PUT URL for `input/{job_id}/source.mp4`, and redirects to the job detail page.
- **Job detail** (`GET /jobs/{job_id}`): Shows upload URL and instructions when status is `created`; shows progress bar with SSE when in progress; shows embedded video player and download button when completed.
- **All jobs** (`GET /jobs`): Unified list of in-progress and completed jobs (from DynamoDB GSIs). Timestamps formatted in user's timezone.
- **Progress events** (`GET /jobs/{job_id}/events`): Server-Sent Events stream of progress percentage and stage label.
- **Play** (`GET /jobs/{job_id}/play`): Redirects to presigned GET URL (legacy; completed jobs use embedded player on detail page).

Presigned URLs use the keys defined in [ARCHITECTURE.md](../../ARCHITECTURE.md): `input/{job_id}/source.mp4` (upload) and `jobs/{job_id}/final.mp4` (playback).

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard |
| GET | `/jobs` | All jobs (in-progress + completed, HTML) |
| POST | `/jobs` | Create job (form: `mode`), redirect to job detail |
| GET | `/jobs/{job_id}` | Job detail (upload form or video + download) |
| GET | `/jobs/{job_id}/events` | SSE progress stream |
| GET | `/jobs/{job_id}/play` | Redirect to presigned playback URL |
| GET | `/static/*` | Static files (favicon, etc.) |

## Dependencies

- **shared-types**: Job, JobStore, ObjectStorage, StereoMode, JobStatus, etc.
- **aws-adapters**: AWS implementations of JobStore and ObjectStorage (DynamoDB, S3). Used when running against real AWS or LocalStack.

The app uses the **JobStore** and **ObjectStorage** abstractions; implementations are injected via `app.state` (tests) or built from environment variables (production).

## Environment variables

When not using mocks (e.g. on ECS or local against AWS), set the same variables as for other packages that use aws-adapters:

- `INPUT_BUCKET_NAME` — input S3 bucket
- `OUTPUT_BUCKET_NAME` — output S3 bucket
- `JOBS_TABLE_NAME` — DynamoDB Jobs table
- `SEGMENT_COMPLETIONS_TABLE_NAME` — DynamoDB SegmentCompletions table (for progress UI)
- `AWS_REGION` (optional)
- `AWS_ENDPOINT_URL` (optional, e.g. LocalStack)

See [packages/aws-adapters/README.md](../aws-adapters/README.md) for the full list. On **ECS**, tasks use an **IAM task role**; no long-lived credentials are required.

**Local development:** Set `STEREOSPOT_ENV_FILE` to the path of a key=value file (e.g. `packages/aws-infra/.env`) to load env vars at startup. The `nx run web-ui:serve` target sets this automatically.

## Local run

```bash
nx run web-ui:serve
```

This loads `packages/aws-infra/.env` (from terraform-output) when `STEREOSPOT_ENV_FILE` is set. No manual env setup needed when using the Nx serve target.

## Tests

```bash
nx run web-ui:test
```

Unit tests use mocked JobStore and ObjectStorage (set on `app.state`) so no AWS or env vars are needed.

## Lint

```bash
nx run web-ui:lint
```
