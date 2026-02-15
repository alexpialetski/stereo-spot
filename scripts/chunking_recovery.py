#!/usr/bin/env python3
"""
Chunking failure recovery: set Job total_segments and status=chunking_complete from S3.

Use when chunking uploaded segments to S3 but the media-worker died before updating
the Job (e.g. crash after upload, before DynamoDB UpdateItem). This script lists
segments in S3 (prefix segments/{job_id}/), derives total_segments using the
segment key parser from shared-types, and performs a single DynamoDB UpdateItem.

Prerequisites:
  - pip install -e packages/shared-types (from repo root)
  - AWS credentials (env or profile)
  - INPUT_BUCKET_NAME, JOBS_TABLE_NAME in env (or load packages/aws-infra/.env)

Usage:
  python scripts/chunking_recovery.py <job_id> [--yes]
"""

import argparse
import os
import sys


def _load_env_file(path: str) -> None:
    """Load key=value file and set os.environ with UPPERCASE keys."""
    if not os.path.isfile(path):
        return
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
    parser = argparse.ArgumentParser(
        description="Recover chunking: set Job total_segments and status=chunking_complete from S3 segments."
    )
    parser.add_argument("job_id", help="Job ID to recover")
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()
    job_id = args.job_id

    # Load env from aws-infra .env if present (repo root relative to script)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    env_file = os.path.join(repo_root, "packages", "aws-infra", ".env")
    _load_env_file(env_file)
    os.environ.setdefault("AWS_REGION", "us-east-1")

    input_bucket = os.environ.get("INPUT_BUCKET_NAME")
    jobs_table = os.environ.get("JOBS_TABLE_NAME")
    if not input_bucket or not jobs_table:
        print("Error: set INPUT_BUCKET_NAME and JOBS_TABLE_NAME (or load packages/aws-infra/.env)", file=sys.stderr)
        return 1

    import boto3
    from stereo_spot_shared import JobStatus, parse_segment_key

    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION"))
    dynamodb = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION"))

    prefix = f"segments/{job_id}/"
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=input_bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key")
            if key and key != prefix.rstrip("/"):
                keys.append(key)

    if not keys:
        print(f"No objects found under s3://{input_bucket}/{prefix}", file=sys.stderr)
        return 1

    # Parse each key with shared-types; derive total_segments (all keys share same total)
    total_segments: int | None = None
    for key in keys:
        payload = parse_segment_key(input_bucket, key)
        if payload is None:
            print(f"Warning: could not parse segment key: {key}", file=sys.stderr)
            continue
        if total_segments is None:
            total_segments = payload.total_segments
        elif payload.total_segments != total_segments:
            print(
                f"Warning: inconsistent total_segments in keys ({total_segments} vs {payload.total_segments})",
                file=sys.stderr,
            )

    if total_segments is None:
        print("Error: no valid segment keys found (format: segments/{job_id}/{i:05d}_{total:05d}_{mode}.mp4)", file=sys.stderr)
        return 1

    # Check current job
    try:
        resp = dynamodb.get_item(
            TableName=jobs_table,
            Key={"job_id": {"S": job_id}},
        )
    except Exception as e:
        print(f"Error getting job: {e}", file=sys.stderr)
        return 1

    item = resp.get("Item")
    if not item:
        print(f"Error: job_id not found in Jobs table: {job_id}", file=sys.stderr)
        return 1

    status = (item.get("status") or {}).get("S") or ""
    if status == JobStatus.CHUNKING_COMPLETE.value or status == JobStatus.COMPLETED.value:
        print(f"Job already has status={status}. Refusing to overwrite.", file=sys.stderr)
        return 1

    if not args.yes:
        print(f"Will set total_segments={total_segments} and status=chunking_complete for job_id={job_id}.")
        try:
            confirm = input("Continue? [y/N]: ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm != "y" and confirm != "yes":
            print("Aborted.")
            return 0

    try:
        dynamodb.update_item(
            TableName=jobs_table,
            Key={"job_id": {"S": job_id}},
            UpdateExpression="SET #st = :st, total_segments = :ts",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":st": {"S": JobStatus.CHUNKING_COMPLETE.value},
                ":ts": {"N": str(total_segments)},
            },
        )
    except Exception as e:
        print(f"Error updating job: {e}", file=sys.stderr)
        return 1

    print(f"Updated job_id={job_id}: total_segments={total_segments}, status=chunking_complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
