#!/usr/bin/env python3
"""
Data plane smoke test for stereo-spot AWS resources.

Requires AWS credentials (env or profile). Load Terraform outputs into env before
running, e.g.:
  export $(grep -v '^#' ../aws-infra/terraform-outputs.env | xargs -I {} sh -c 'echo {}' | sed 's/^/export /' | sed 's/=/="/' | sed 's/$/"/')
  # then uppercase the keys, or use SMOKE_TEST_ENV_FILE (see below)

Or set SMOKE_TEST_ENV_FILE to a path to terraform-outputs.env (key=value, one per line).
This script will load it and set UPPERCASE env vars so env_config works.
"""

import os
import sys


def _load_env_file(path: str) -> None:
    """Load key=value file and set os.environ with UPPERCASE keys."""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip().upper()
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value


def main() -> int:
    env_file = os.environ.get("SMOKE_TEST_ENV_FILE")
    if env_file and os.path.isfile(env_file):
        _load_env_file(env_file)
    # boto3 requires a region; default to us-east-1 if not set (e.g. terraform-outputs.env has no region)
    os.environ.setdefault("AWS_REGION", "us-east-1")

    # Import after env is set so env_config reads correct values
    from stereo_spot_shared import (
        ChunkingPayload,
        Job,
        JobStatus,
        ReassemblyPayload,
        StereoMode,
        VideoWorkerPayload,
    )
    from stereo_spot_aws_adapters.env_config import (
        input_bucket_name,
        job_store_from_env,
        object_storage_from_env,
        output_bucket_name,
    )
    from stereo_spot_aws_adapters.env_config import (
        chunking_queue_sender_from_env,
        reassembly_queue_sender_from_env,
        video_worker_queue_sender_from_env,
    )

    job_id = "smoke-test-job"
    input_bucket = input_bucket_name()
    output_bucket = output_bucket_name()

    print("1. Creating Job in DynamoDB...")
    job_store = job_store_from_env()
    job = Job(
        job_id=job_id,
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CREATED,
        created_at=0,
    )
    job_store.put(job)
    got = job_store.get(job_id)
    assert got is not None and got.job_id == job_id
    print("   Job created.")

    print("2. Sending one message to each SQS queue...")
    chunking_sender = chunking_queue_sender_from_env()
    video_sender = video_worker_queue_sender_from_env()
    reassembly_sender = reassembly_queue_sender_from_env()

    chunking_sender.send(
        ChunkingPayload(bucket=input_bucket, key=f"input/{job_id}/source.mp4").model_dump_json()
    )
    video_sender.send(
        VideoWorkerPayload(
            job_id=job_id,
            segment_index=0,
            total_segments=1,
            segment_s3_uri=f"s3://{input_bucket}/segments/{job_id}/00000_00001_anaglyph.mp4",
            mode=StereoMode.ANAGLYPH,
        ).model_dump_json()
    )
    reassembly_sender.send(ReassemblyPayload(job_id=job_id).model_dump_json())
    print("   Messages sent.")

    print("3. Verifying S3 presigned upload and download...")
    storage = object_storage_from_env()
    upload_url = storage.presign_upload(input_bucket, f"input/{job_id}/source.mp4", expires_in=60)
    download_url = storage.presign_download(output_bucket, f"jobs/{job_id}/final.mp4", expires_in=60)
    assert "input/" in upload_url or "X-Amz-" in upload_url
    assert "jobs/" in download_url or "X-Amz-" in download_url

    # Actually upload and download a few bytes to verify
    storage.upload(input_bucket, f"input/{job_id}/smoke-test-object", b"smoke")
    data = storage.download(input_bucket, f"input/{job_id}/smoke-test-object")
    assert data == b"smoke"
    print("   Presign and upload/download verified.")

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
