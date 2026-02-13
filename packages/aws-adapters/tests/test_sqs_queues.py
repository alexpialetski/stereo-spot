"""Tests for SQS QueueSender and QueueReceiver."""

from stereo_spot_aws_adapters import SQSQueueReceiver, SQSQueueSender


class TestSQSQueueSenderAndReceiver:
    """Tests for SQS queue send/receive/delete."""

    def test_send_and_receive_str(self, sqs_queue):
        sender = SQSQueueSender(sqs_queue, region_name="us-east-1")
        receiver = SQSQueueReceiver(sqs_queue, region_name="us-east-1")
        sender.send('{"bucket":"b","key":"k"}')
        messages = receiver.receive(max_messages=5)
        assert len(messages) == 1
        assert messages[0].body == '{"bucket":"b","key":"k"}'
        receiver.delete(messages[0].receipt_handle)
        assert receiver.receive(max_messages=5) == []

    def test_send_and_receive_bytes(self, sqs_queue):
        sender = SQSQueueSender(sqs_queue, region_name="us-east-1")
        receiver = SQSQueueReceiver(sqs_queue, region_name="us-east-1")
        payload = b"binary \xff\xfe"
        sender.send(payload)
        messages = receiver.receive(max_messages=5)
        assert len(messages) == 1
        import base64
        assert base64.b64decode(messages[0].body.encode("ascii")) == payload

    def test_receive_empty_returns_empty_list(self, sqs_queue):
        receiver = SQSQueueReceiver(sqs_queue, region_name="us-east-1")
        assert receiver.receive(max_messages=1) == []
