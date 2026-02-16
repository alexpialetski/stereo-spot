"""Tests for DynamoDB JobStore, SegmentCompletionStore, and ReassemblyTriggeredLock."""

import boto3
from stereo_spot_shared import Job, JobListItem, JobStatus, SegmentCompletion, StereoMode

from stereo_spot_aws_adapters import (
    DynamoDBJobStore,
    DynamoSegmentCompletionStore,
    ReassemblyTriggeredLock,
)


class TestDynamoDBJobStore:
    """Tests for DynamoDBJobStore."""

    def test_put_and_get(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        job = Job(
            job_id="job-1",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
            created_at=1000,
        )
        store.put(job)
        got = store.get("job-1")
        assert got is not None
        assert got.job_id == "job-1"
        assert got.mode == StereoMode.ANAGLYPH
        assert got.status == JobStatus.CREATED
        assert got.created_at == 1000

    def test_get_missing_returns_none(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        assert store.get("nonexistent") is None

    def test_update(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        job = Job(
            job_id="job-2",
            mode=StereoMode.SBS,
            status=JobStatus.CHUNKING_IN_PROGRESS,
            created_at=2000,
        )
        store.put(job)
        store.update("job-2", status=JobStatus.CHUNKING_COMPLETE.value, total_segments=10)
        got = store.get("job-2")
        assert got is not None
        assert got.status == JobStatus.CHUNKING_COMPLETE
        assert got.total_segments == 10

    def test_list_completed(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        for i, jid in enumerate(["j1", "j2", "j3"]):
            store.put(
                Job(
                    job_id=jid,
                    mode=StereoMode.ANAGLYPH,
                    status=JobStatus.COMPLETED,
                    created_at=1000 + i,
                    completed_at=2000 + i,
                )
            )
        items, next_key = store.list_completed(limit=10)
        assert len(items) == 3
        assert all(isinstance(x, JobListItem) for x in items)
        assert [x.job_id for x in items] == ["j3", "j2", "j1"]
        assert next_key is None

    def test_list_completed_excludes_non_completed(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        store.put(
            Job(
                job_id="created",
                mode=StereoMode.SBS,
                status=JobStatus.CREATED,
                created_at=1000,
            )
        )
        store.put(
            Job(
                job_id="done",
                mode=StereoMode.SBS,
                status=JobStatus.COMPLETED,
                created_at=1000,
                completed_at=2000,
            )
        )
        items, _ = store.list_completed(limit=10)
        assert len(items) == 1
        assert items[0].job_id == "done"

    def test_list_in_progress(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        store.put(
            Job(
                job_id="ip1",
                mode=StereoMode.ANAGLYPH,
                status=JobStatus.CREATED,
                created_at=1000,
            )
        )
        store.put(
            Job(
                job_id="ip2",
                mode=StereoMode.SBS,
                status=JobStatus.CHUNKING_IN_PROGRESS,
                created_at=2000,
            )
        )
        store.put(
            Job(
                job_id="done",
                mode=StereoMode.ANAGLYPH,
                status=JobStatus.COMPLETED,
                created_at=500,
                completed_at=3000,
            )
        )
        items = store.list_in_progress(limit=10)
        assert len(items) == 2
        assert [x.job_id for x in items] == ["ip2", "ip1"]


class TestDynamoSegmentCompletionStore:
    """Tests for DynamoSegmentCompletionStore."""

    def test_put_and_query(self, segment_completions_table):
        store = DynamoSegmentCompletionStore(
            segment_completions_table, region_name="us-east-1"
        )
        c1 = SegmentCompletion(
            job_id="job-1",
            segment_index=0,
            output_s3_uri="s3://out/jobs/job-1/segments/0.mp4",
            completed_at=3000,
        )
        c2 = SegmentCompletion(
            job_id="job-1",
            segment_index=1,
            output_s3_uri="s3://out/jobs/job-1/segments/1.mp4",
            completed_at=3001,
        )
        store.put(c1)
        store.put(c2)
        results = store.query_by_job("job-1")
        assert len(results) == 2
        assert results[0].segment_index == 0
        assert results[1].segment_index == 1

    def test_query_empty_returns_empty_list(self, segment_completions_table):
        store = DynamoSegmentCompletionStore(
            segment_completions_table, region_name="us-east-1"
        )
        assert store.query_by_job("no-job") == []


class TestReassemblyTriggeredLock:
    """Tests for ReassemblyTriggeredLock (conditional update for single-run guarantee)."""

    def test_try_acquire_when_item_missing_returns_false(
        self, reassembly_triggered_table
    ):
        lock = ReassemblyTriggeredLock(
            reassembly_triggered_table, region_name="us-east-1"
        )
        assert lock.try_acquire("job-1") is False

    def test_try_acquire_when_item_exists_succeeds(self, reassembly_triggered_table):
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(
            reassembly_triggered_table
        )
        table.put_item(Item={"job_id": "job-1", "triggered_at": 12345})
        lock = ReassemblyTriggeredLock(
            reassembly_triggered_table, region_name="us-east-1"
        )
        assert lock.try_acquire("job-1") is True
        item = table.get_item(Key={"job_id": "job-1"})["Item"]
        assert "reassembly_started_at" in item

    def test_try_acquire_second_time_returns_false(self, reassembly_triggered_table):
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(
            reassembly_triggered_table
        )
        table.put_item(Item={"job_id": "job-2", "triggered_at": 12345})
        lock = ReassemblyTriggeredLock(
            reassembly_triggered_table, region_name="us-east-1"
        )
        assert lock.try_acquire("job-2") is True
        assert lock.try_acquire("job-2") is False
