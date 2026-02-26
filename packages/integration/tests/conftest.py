"""
Pytest fixtures for integration tests: moto-backed AWS resources and env setup.

All resource names and queue URLs are set in os.environ so that env_config in
aws-adapters and the web-ui/workers use the same resources when tests run.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from moto import mock_aws


@pytest.fixture(scope="function")
def aws_credentials() -> None:
    """Set fake AWS credentials for moto and platform for adapters facade."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["PLATFORM"] = "aws"


@pytest.fixture
def moto_aws(aws_credentials: None) -> None:
    """Enable moto mock for DynamoDB, SQS, S3."""
    with mock_aws():
        yield


def _create_jobs_table(client: object) -> str:
    client.create_table(
        TableName="int-test-jobs",
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "job_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "completed_at", "AttributeType": "N"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "status-completed_at",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "completed_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    return "int-test-jobs"


def _create_segment_completions_table(client: object) -> str:
    client.create_table(
        TableName="int-test-segment-completions",
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "job_id", "KeyType": "HASH"},
            {"AttributeName": "segment_index", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "job_id", "AttributeType": "S"},
            {"AttributeName": "segment_index", "AttributeType": "N"},
        ],
    )
    return "int-test-segment-completions"


def _create_reassembly_triggered_table(client: object) -> str:
    client.create_table(
        TableName="int-test-reassembly-triggered",
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
    )
    return "int-test-reassembly-triggered"


def _create_inference_invocations_table(client: object) -> str:
    client.create_table(
        TableName="int-test-inference-invocations",
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "output_location", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "output_location", "AttributeType": "S"}],
    )
    return "int-test-inference-invocations"


@pytest.fixture
def integration_env(moto_aws: None) -> dict[str, str]:
    """
    Create DynamoDB tables, SQS queues, S3 buckets and set os.environ.
    Returns a dict of the resource names/URLs for use in tests.
    """
    import boto3

    region = "us-east-1"
    dynamodb = boto3.client("dynamodb", region_name=region)
    sqs = boto3.client("sqs", region_name=region)
    s3 = boto3.client("s3", region_name=region)

    jobs_table = _create_jobs_table(dynamodb)
    segment_completions_table = _create_segment_completions_table(dynamodb)
    reassembly_triggered_table = _create_reassembly_triggered_table(dynamodb)
    inference_invocations_table = _create_inference_invocations_table(dynamodb)

    chunking_resp = sqs.create_queue(QueueName="int-test-chunking")
    chunking_queue_url = chunking_resp["QueueUrl"]
    video_worker_resp = sqs.create_queue(QueueName="int-test-video-worker")
    video_worker_queue_url = video_worker_resp["QueueUrl"]
    reassembly_resp = sqs.create_queue(QueueName="int-test-reassembly")
    reassembly_queue_url = reassembly_resp["QueueUrl"]
    output_events_resp = sqs.create_queue(QueueName="int-test-output-events")
    output_events_queue_url = output_events_resp["QueueUrl"]
    job_status_events_resp = sqs.create_queue(QueueName="int-test-job-status-events")
    job_status_events_queue_url = job_status_events_resp["QueueUrl"]
    deletion_resp = sqs.create_queue(QueueName="int-test-deletion")
    deletion_queue_url = deletion_resp["QueueUrl"]
    ingest_resp = sqs.create_queue(QueueName="int-test-ingest")
    ingest_queue_url = ingest_resp["QueueUrl"]

    input_bucket = "int-test-input-bucket"
    output_bucket = "int-test-output-bucket"
    s3.create_bucket(Bucket=input_bucket)
    s3.create_bucket(Bucket=output_bucket)

    env = {
        "JOBS_TABLE_NAME": jobs_table,
        "SEGMENT_COMPLETIONS_TABLE_NAME": segment_completions_table,
        "REASSEMBLY_TRIGGERED_TABLE_NAME": reassembly_triggered_table,
        "INFERENCE_INVOCATIONS_TABLE_NAME": inference_invocations_table,
        "CHUNKING_QUEUE_URL": chunking_queue_url,
        "VIDEO_WORKER_QUEUE_URL": video_worker_queue_url,
        "OUTPUT_EVENTS_QUEUE_URL": output_events_queue_url,
        "JOB_STATUS_EVENTS_QUEUE_URL": job_status_events_queue_url,
        "REASSEMBLY_QUEUE_URL": reassembly_queue_url,
        "DELETION_QUEUE_URL": deletion_queue_url,
        "INGEST_QUEUE_URL": ingest_queue_url,
        "INPUT_BUCKET_NAME": input_bucket,
        "OUTPUT_BUCKET_NAME": output_bucket,
        "AWS_REGION": region,
    }
    for k, v in env.items():
        os.environ[k] = v
    yield env
    # Teardown: remove env vars we set (optional; tests run in isolation)
    for k in env:
        os.environ.pop(k, None)


def make_minimal_mp4(path: str | Path, duration_sec: float = 1.0) -> bool:
    """
    Create a minimal valid MP4 file using ffmpeg (e.g. 1 second of black video).
    Returns True if the file was created, False if ffmpeg is not available.
    """
    path = Path(path)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s=320x240:d={duration_sec}",
                "-t",
                str(duration_sec),
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-f",
                "mp4",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return path.exists()


@pytest.fixture
def minimal_mp4_path() -> Path | None:
    """
    Create a minimal valid MP4 (1 second) in a temp file.
    Returns the path, or None if ffmpeg is not available.
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        path = Path(f.name)
    if make_minimal_mp4(path, duration_sec=1.0):
        yield path
    else:
        path.unlink(missing_ok=True)
        yield None
    path.unlink(missing_ok=True)
