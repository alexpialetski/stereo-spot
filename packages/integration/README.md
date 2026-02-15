# Stereo-Spot Integration Tests

End-to-end and integration tests for the stereo-spot pipeline (Step 5.1).

## Purpose

- **E2E pipeline test:** Create job via web-ui API → upload source → chunking → video-worker (stub) → reassembly trigger (simulated) → reassembly → assert Job completed and `final.mp4` exists.
- **Reassembly idempotency test:** Send two reassembly messages for the same job; assert exactly one run produces `final.mp4`, the other skips without overwriting.

Tests use **moto** to mock AWS (DynamoDB, SQS, S3); no real AWS or LocalStack required. The E2E test requires **ffmpeg** to generate a minimal source video and to run chunking/reassembly.

## Running tests

From the repo root:

```bash
nx run integration:test
```

This installs shared-types, aws-adapters, web-ui, media-worker, video-worker, reassembly-trigger, and this package, then runs pytest.

## Prerequisites

- **ffmpeg** must be on `PATH` for the E2E and idempotency tests (they are skipped if ffmpeg is not found).
- No AWS credentials needed (moto is used).

## CI

Run `nx run integration:test` when integration is enabled (e.g. on every PR or in a scheduled job). See [TESTING.md](../../docs/TESTING.md).
