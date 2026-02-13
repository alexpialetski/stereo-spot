"""SQS implementations of QueueSender and QueueReceiver."""

import base64

import boto3
from stereo_spot_shared.interfaces import QueueMessage


def _encode_body(body: str | bytes) -> str:
    """Encode body for SQS (SQS MessageBody must be string)."""
    if isinstance(body, bytes):
        return base64.b64encode(body).decode("ascii")
    return body


def _decode_body(body: str, was_bytes: bool = False) -> str | bytes:
    """Decode SQS body back to str or bytes."""
    if was_bytes:
        return base64.b64decode(body.encode("ascii"))
    return body


class SQSQueueSender:
    """QueueSender implementation using SQS."""

    def __init__(
        self,
        queue_url: str,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._queue_url = queue_url
        self._client = boto3.client(
            "sqs",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    def send(self, body: str | bytes) -> None:
        """Send one message with the given body."""
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=_encode_body(body),
        )


class SQSQueueReceiver:
    """QueueReceiver implementation using SQS."""

    def __init__(
        self,
        queue_url: str,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        wait_time_seconds: int = 0,
    ) -> None:
        self._queue_url = queue_url
        self._wait_time_seconds = wait_time_seconds
        self._client = boto3.client(
            "sqs",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    def receive(self, max_messages: int = 1) -> list[QueueMessage]:
        """Receive up to max_messages. Returns empty list if none available."""
        resp = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=min(max_messages, 10),
            WaitTimeSeconds=self._wait_time_seconds,
            AttributeNames=["All"],
        )
        messages = resp.get("Messages") or []
        result = []
        for msg in messages:
            body = msg["Body"]
            result.append(QueueMessage(receipt_handle=msg["ReceiptHandle"], body=body))
        return result

    def delete(self, receipt_handle: str) -> None:
        """Delete a message by its receipt handle after successful processing."""
        self._client.delete_message(
            QueueUrl=self._queue_url,
            ReceiptHandle=receipt_handle,
        )
