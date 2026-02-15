# shared-types

Shared Python library for the **stereo-spot** pipeline. Single source of truth for job, segment, and message shapes used by the web-ui, media-worker, video-worker, and Lambda (e.g. reassembly trigger).

- **Format:** Pydantic models for validation and serialization.
- **Consumers:** All Python app and worker packages depend on this library.
- **Cloud abstractions:** Thin interfaces for job store, segment-completion store, queues, and object storage (see [docs/SHARED_TYPES.md](../../docs/SHARED_TYPES.md) in the repo for interface descriptions and consumers).

## Install locally

From the repo root:

```bash
pip install -e packages/shared-types
```

Or from this directory:

```bash
pip install -e .
```

For development (pytest, ruff, build):

```bash
pip install -e ".[dev]"
```

## Run tests

```bash
# From repo root via Nx (recommended)
nx run shared-types:test

# From this directory
cd packages/shared-types && pytest -v
```

## Lint

```bash
nx run shared-types:lint
# or: ruff check src tests
```

## Build (sdist/wheel)

```bash
nx run shared-types:build
# or: python -m build
```

Build artifacts appear in `dist/`. Other packages can depend on the built wheel in CI.

---

## Models summary

| Model | Purpose |
|-------|--------|
| `Job` | Job record (DynamoDB Jobs table): `job_id`, `mode`, `status`, `created_at`, `total_segments`, `completed_at`. |
| `JobStatus` | Enum: `created`, `chunking_in_progress`, `chunking_complete`, `completed`. |
| `StereoMode` | Enum: `anaglyph`, `sbs`. |
| `VideoWorkerPayload` / `SegmentKeyPayload` | Canonical segment payload: `job_id`, `segment_index`, `total_segments`, `segment_s3_uri`, `mode`. From segment key parser or S3 event. |
| `SegmentCompletion` | DynamoDB SegmentCompletions: `job_id`, `segment_index`, `output_s3_uri`, `completed_at`. |
| `ChunkingPayload` | Raw S3 event for chunking queue: `bucket`, `key`. Worker parses `job_id` from key and fetches `mode` from DynamoDB. |
| `ReassemblyPayload` | Reassembly queue message: `job_id`. |
| `CreateJobRequest` / `CreateJobResponse` | API: create job (mode) → job_id, upload_url. |
| `JobListItem` | API: list completed jobs (job_id, mode, completed_at). |
| `PresignedPlaybackResponse` | API: playback_url for `jobs/{job_id}/final.mp4`. |

---

## Key conventions and parsers

**Segment key format (single source of truth):**

```
segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4
```

Example: `segments/job-abc/00042_00100_anaglyph.mp4`. Zero-padding keeps lexicographic order. The **parser and builder live only in this package**; media-worker uses `build_segment_key()`, video-worker uses `parse_segment_key()`.

- **`build_segment_key(job_id, segment_index, total_segments, mode)`** → key string.
- **`parse_segment_key(bucket, key)`** → `VideoWorkerPayload` or `None` if the key is invalid. Invalid keys return `None` (no exception).

**Input key format (source upload):**

```
input/{job_id}/source.mp4
```

- **`parse_input_key(key)`** → `job_id` string or `None` if the key is invalid. Used by the chunking worker to get `job_id` from the S3 event.
