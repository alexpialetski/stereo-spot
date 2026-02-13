"""AWS implementations of stereo-spot cloud interfaces."""

from .dynamodb_stores import DynamoDBJobStore, DynamoSegmentCompletionStore
from .s3_storage import S3ObjectStorage
from .sqs_queues import SQSQueueReceiver, SQSQueueSender

__all__ = [
    "DynamoDBJobStore",
    "DynamoSegmentCompletionStore",
    "S3ObjectStorage",
    "SQSQueueReceiver",
    "SQSQueueSender",
]
