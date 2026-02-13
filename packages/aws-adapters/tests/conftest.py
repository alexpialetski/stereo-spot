"""Pytest fixtures for aws-adapters tests (moto-backed AWS resources)."""

import os

import pytest
from moto import mock_aws


@pytest.fixture(scope="function")
def aws_credentials():
    """Set fake AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def moto_aws(aws_credentials):
    """Enable moto mock for DynamoDB, SQS, S3."""
    with mock_aws():
        yield


@pytest.fixture
def jobs_table(moto_aws):
    """Create Jobs DynamoDB table matching Terraform schema (with GSI)."""
    import boto3

    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName="test-jobs",
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
    return "test-jobs"


@pytest.fixture
def segment_completions_table(moto_aws):
    """Create SegmentCompletions DynamoDB table matching Terraform schema."""
    import boto3

    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName="test-segment-completions",
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
    return "test-segment-completions"


@pytest.fixture
def sqs_queue(moto_aws):
    """Create an SQS queue and return its URL."""
    import boto3

    client = boto3.client("sqs", region_name="us-east-1")
    resp = client.create_queue(QueueName="test-queue")
    return resp["QueueUrl"]


@pytest.fixture
def s3_buckets(moto_aws):
    """Create input and output S3 buckets."""
    import boto3

    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="test-input-bucket")
    client.create_bucket(Bucket="test-output-bucket")
    return "test-input-bucket", "test-output-bucket"
