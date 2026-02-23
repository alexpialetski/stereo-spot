"""Tests for job_events normalizer and sink."""

import json

import pytest
from stereo_spot_shared import JobEvent, JobTableChange, SegmentCompletionInsert

from stereo_spot_aws_adapters.job_events import (
    SQSJobEventsSink,
    get_aws_adapter,
    normalize_dynamodb_stream_record,
)


def test_normalize_jobs_stream_record():
    """DynamoDB stream record from jobs table -> JobTableChange."""
    jobs_arn = "arn:aws:dynamodb:us-east-1:123:table/foo-jobs/stream/2024-01-01T00:00:00"
    record = {
        "eventSourceARN": jobs_arn,
        "eventName": "MODIFY",
        "dynamodb": {
            "NewImage": {
                "job_id": {"S": "job-1"},
                "mode": {"S": "sbs"},
                "status": {"S": "completed"},
                "completed_at": {"N": "12345"},
                "title": {"S": "My Video"},
            }
        },
    }
    out = normalize_dynamodb_stream_record(
        record,
        jobs_stream_arn=jobs_arn,
        segment_completions_stream_arn=None,
    )
    assert isinstance(out, JobTableChange)
    assert out.job_id == "job-1"
    assert out.new_image["status"] == "completed"
    assert out.new_image["completed_at"] == 12345
    assert out.new_image["title"] == "My Video"


def test_normalize_segment_completions_stream_record():
    """DynamoDB stream record from segment_completions table -> SegmentCompletionInsert."""
    seg_arn = "arn:aws:dynamodb:us-east-1:123:table/foo-segment-completions/stream/2024-01-01"
    record = {
        "eventSourceARN": seg_arn,
        "eventName": "INSERT",
        "dynamodb": {
            "NewImage": {
                "job_id": {"S": "job-2"},
                "segment_index": {"N": "3"},
            }
        },
    }
    out = normalize_dynamodb_stream_record(
        record,
        jobs_stream_arn="arn:aws:other",
        segment_completions_stream_arn=seg_arn,
    )
    assert isinstance(out, SegmentCompletionInsert)
    assert out.job_id == "job-2"
    assert out.segment_index == 3


def test_normalize_segment_completions_modify_ignored():
    """Segment completions MODIFY (not INSERT) -> None."""
    seg_arn = "arn:aws:dynamodb:us-east-1:123:table/foo-segment-completions/stream/2024-01-01"
    record = {
        "eventSourceARN": seg_arn,
        "eventName": "MODIFY",
        "dynamodb": {"NewImage": {"job_id": {"S": "j"}, "segment_index": {"N": "0"}}},
    }
    out = normalize_dynamodb_stream_record(
        record,
        jobs_stream_arn="other",
        segment_completions_stream_arn=seg_arn,
    )
    assert out is None


def test_normalize_no_new_image_returns_none():
    """Record without NewImage -> None."""
    out = normalize_dynamodb_stream_record(
        {"eventSourceARN": "arn:aws:jobs/stream", "eventName": "REMOVE", "dynamodb": {}},
        jobs_stream_arn="arn:aws:jobs/stream",
        segment_completions_stream_arn=None,
    )
    assert out is None


def test_sqs_job_events_sink_sends_json(monkeypatch):
    """SQSJobEventsSink.send serializes JobEvent and calls SQS."""
    sent = []

    class FakeSender:
        def send(self, body: str | bytes) -> None:
            sent.append(body)

    monkeypatch.setattr(
        "stereo_spot_aws_adapters.job_events.SQSQueueSender",
        lambda *a, **k: FakeSender(),
    )
    sink = SQSJobEventsSink("https://sqs.us-east-1.amazonaws.com/123/queue")
    ev = JobEvent(
        job_id="j1",
        status="completed",
        progress_percent=100,
        stage_label="Completed",
        title="Test",
        completed_at=999,
    )
    sink.send(ev)
    assert len(sent) == 1
    payload = json.loads(sent[0])
    assert payload["job_id"] == "j1"
    assert payload["status"] == "completed"
    assert payload["progress_percent"] == 100
    assert payload["title"] == "Test"


def test_get_aws_adapter_requires_queue_url(monkeypatch):
    """get_aws_adapter raises if JOB_EVENTS_QUEUE_URL not set."""
    monkeypatch.delenv("JOB_EVENTS_QUEUE_URL", raising=False)
    with pytest.raises(KeyError):
        get_aws_adapter()


def test_get_aws_adapter_returns_adapter_with_normalizer_and_stores(monkeypatch):
    """get_aws_adapter returns object with normalizer, job_store, segment_store, sink."""
    monkeypatch.setenv("JOB_EVENTS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/q")
    monkeypatch.setenv("JOBS_TABLE_NAME", "jobs-table")
    monkeypatch.setenv("SEGMENT_COMPLETIONS_TABLE_NAME", "seg-table")
    monkeypatch.setenv("JOBS_TABLE_STREAM_ARN", "arn:jobs")
    monkeypatch.setenv("SEGMENT_COMPLETIONS_TABLE_STREAM_ARN", "arn:seg")

    adapter = get_aws_adapter()
    assert hasattr(adapter, "normalizer")
    assert hasattr(adapter, "job_store")
    assert hasattr(adapter, "segment_store")
    assert hasattr(adapter, "sink")
    assert callable(adapter.normalizer)
