"""Tests for Lambda handler: trigger when complete, no trigger when not, no duplicate."""

from unittest.mock import MagicMock, patch

from reassembly_trigger.handler import (
    _get_job_ids_from_stream_records,
    process_job_id,
    should_trigger_reassembly,
)


def test_get_job_ids_from_stream_records() -> None:
    records = [
        {"dynamodb": {"Keys": {"job_id": {"S": "job-1"}, "segment_index": {"N": "0"}}}},
        {"dynamodb": {"Keys": {"job_id": {"S": "job-1"}, "segment_index": {"N": "1"}}}},
        {"dynamodb": {"Keys": {"job_id": {"S": "job-2"}, "segment_index": {"N": "0"}}}},
    ]
    assert _get_job_ids_from_stream_records(records) == {"job-1", "job-2"}


def test_get_job_ids_empty_records() -> None:
    assert _get_job_ids_from_stream_records([]) == set()


def test_should_trigger_reassembly_true() -> None:
    """When job is chunking_complete and count == total_segments, return True."""
    with patch(
        "reassembly_trigger.handler._get_job",
        return_value={
            "job_id": "j1",
            "mode": "anaglyph",
            "status": "chunking_complete",
            "total_segments": 3,
        },
    ), patch(
        "reassembly_trigger.handler._count_segment_completions",
        return_value=3,
    ):
        assert (
            should_trigger_reassembly(
                "jobs-table",
                "segment-completions-table",
                "j1",
            )
            is True
        )


def test_should_trigger_reassembly_count_not_reached() -> None:
    """No trigger when count < total_segments."""
    with patch(
        "reassembly_trigger.handler._get_job",
        return_value={
            "job_id": "j1",
            "mode": "anaglyph",
            "status": "chunking_complete",
            "total_segments": 3,
        },
    ), patch(
        "reassembly_trigger.handler._count_segment_completions",
        return_value=2,
    ):
        assert (
            should_trigger_reassembly(
                "jobs-table",
                "segment-completions-table",
                "j1",
            )
            is False
        )


def test_should_trigger_reassembly_job_not_chunking_complete() -> None:
    """No trigger when status is not chunking_complete."""
    with patch(
        "reassembly_trigger.handler._get_job",
        return_value={
            "job_id": "j1",
            "mode": "anaglyph",
            "status": "chunking_in_progress",
            "total_segments": 2,
        },
    ), patch(
        "reassembly_trigger.handler._count_segment_completions",
        return_value=2,
    ):
        assert (
            should_trigger_reassembly(
                "jobs-table",
                "segment-completions-table",
                "j1",
            )
            is False
        )


def test_should_trigger_reassembly_job_missing() -> None:
    with patch("reassembly_trigger.handler._get_job", return_value=None):
        assert (
            should_trigger_reassembly(
                "jobs-table",
                "segment-completions-table",
                "missing",
            )
            is False
        )


def test_process_job_id_sends_when_conditional_create_succeeds() -> None:
    """When should_trigger and conditional create succeeds, send message to SQS."""
    with patch(
        "reassembly_trigger.handler.should_trigger_reassembly",
        return_value=True,
    ), patch(
        "reassembly_trigger.handler._conditional_create_reassembly_triggered",
        return_value=True,
    ), patch(
        "reassembly_trigger.handler._send_reassembly_message",
    ) as send:
        process_job_id(
            "j1",
            "jobs-table",
            "segment-completions-table",
            "reassembly-triggered-table",
            "https://sqs.us-east-1.amazonaws.com/123/reassembly",
        )
        send.assert_called_once()
        (args, kwargs) = send.call_args
        assert args[0] == "https://sqs.us-east-1.amazonaws.com/123/reassembly"
        assert args[1] == "j1"


def test_process_job_id_no_send_when_conditional_create_fails() -> None:
    """When ReassemblyTriggered already exists (conditional create fails), do not send."""
    with patch(
        "reassembly_trigger.handler.should_trigger_reassembly",
        return_value=True,
    ), patch(
        "reassembly_trigger.handler._conditional_create_reassembly_triggered",
        return_value=False,
    ), patch(
        "reassembly_trigger.handler._send_reassembly_message",
    ) as send:
        process_job_id(
            "j1",
            "jobs-table",
            "segment-completions-table",
            "reassembly-triggered-table",
            "https://sqs.us-east-1.amazonaws.com/123/reassembly",
        )
        send.assert_not_called()


def test_process_job_id_no_send_when_should_trigger_false() -> None:
    with patch(
        "reassembly_trigger.handler.should_trigger_reassembly",
        return_value=False,
    ), patch(
        "reassembly_trigger.handler._conditional_create_reassembly_triggered",
    ) as cond_create, patch(
        "reassembly_trigger.handler._send_reassembly_message",
    ) as send:
        process_job_id(
            "j1",
            "jobs-table",
            "segment-completions-table",
            "reassembly-triggered-table",
            "https://sqs.us-east-1.amazonaws.com/123/reassembly",
        )
        cond_create.assert_not_called()
        send.assert_not_called()


def test_lambda_handler_calls_process_for_each_job_id() -> None:
    """lambda_handler extracts job_ids and processes each."""
    from reassembly_trigger.handler import lambda_handler

    event = {
        "Records": [
            {"dynamodb": {"Keys": {"job_id": {"S": "job-a"}, "segment_index": {"N": "0"}}}},
        ]
    }
    with patch.dict(
        "os.environ",
        {
            "JOBS_TABLE_NAME": "jobs",
            "SEGMENT_COMPLETIONS_TABLE_NAME": "sc",
            "REASSEMBLY_TRIGGERED_TABLE_NAME": "rt",
            "REASSEMBLY_QUEUE_URL": "https://sqs.example.com/q",
        },
    ), patch(
        "reassembly_trigger.handler.process_job_id",
    ) as process, patch(
        "reassembly_trigger.handler.boto3.client",
        return_value=MagicMock(),
    ):
        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        process.assert_called_once()
        call_args = process.call_args[0]
        assert call_args[0] == "job-a"
