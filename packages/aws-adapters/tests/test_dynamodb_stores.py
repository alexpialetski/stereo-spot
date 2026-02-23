"""Tests for DynamoDB JobStore, SegmentCompletionStore, and ReassemblyTriggeredLock."""

import boto3
from stereo_spot_shared import Job, JobListItem, JobStatus, SegmentCompletion, StereoMode

from stereo_spot_aws_adapters import (
    DynamoDBJobStore,
    DynamoSegmentCompletionStore,
    InferenceInvocationsStore,
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

    def test_put_and_get_with_title(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        job = Job(
            job_id="job-title-1",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
            created_at=1000,
            title="attack-on-titan",
        )
        store.put(job)
        got = store.get("job-title-1")
        assert got is not None
        assert got.title == "attack-on-titan"

    def test_update_title(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        job = Job(
            job_id="job-title-2",
            mode=StereoMode.SBS,
            status=JobStatus.CREATED,
            created_at=2000,
        )
        store.put(job)
        store.update("job-title-2", title="my-video")
        got = store.get("job-title-2")
        assert got is not None
        assert got.title == "my-video"

    def test_list_completed_includes_title(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        store.put(
            Job(
                job_id="completed-with-title",
                mode=StereoMode.ANAGLYPH,
                status=JobStatus.COMPLETED,
                created_at=1000,
                completed_at=2000,
                title="attack-on-titan",
            )
        )
        items, _ = store.list_completed(limit=10)
        assert len(items) == 1
        assert items[0].job_id == "completed-with-title"
        assert items[0].title == "attack-on-titan"

    def test_put_and_get_with_uploaded_at_and_size(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        job = Job(
            job_id="job-timing-1",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
            created_at=1000,
            uploaded_at=1005,
            source_file_size_bytes=50_000_000,
        )
        store.put(job)
        got = store.get("job-timing-1")
        assert got is not None
        assert got.uploaded_at == 1005
        assert got.source_file_size_bytes == 50_000_000

    def test_update_uploaded_at_and_source_file_size_bytes(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        job = Job(
            job_id="job-timing-2",
            mode=StereoMode.SBS,
            status=JobStatus.CREATED,
            created_at=2000,
        )
        store.put(job)
        store.update(
            "job-timing-2",
            uploaded_at=2010,
            source_file_size_bytes=100_000_000,
        )
        got = store.get("job-timing-2")
        assert got is not None
        assert got.uploaded_at == 2010
        assert got.source_file_size_bytes == 100_000_000

    def test_list_completed_includes_uploaded_at_and_size(self, jobs_table):
        store = DynamoDBJobStore(jobs_table, region_name="us-east-1")
        store.put(
            Job(
                job_id="completed-with-timing",
                mode=StereoMode.ANAGLYPH,
                status=JobStatus.COMPLETED,
                created_at=1000,
                completed_at=2000,
                uploaded_at=1005,
                source_file_size_bytes=25_000_000,
            )
        )
        items, _ = store.list_completed(limit=10)
        assert len(items) == 1
        assert items[0].job_id == "completed-with-timing"
        assert items[0].uploaded_at == 1005
        assert items[0].source_file_size_bytes == 25_000_000

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
                job_id="ip3",
                mode=StereoMode.ANAGLYPH,
                status=JobStatus.INGESTING,
                created_at=1500,
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
        assert len(items) == 3
        assert [x.job_id for x in items] == ["ip2", "ip3", "ip1"]


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

    def test_try_create_triggered_first_call_returns_true(
        self, reassembly_triggered_table
    ):
        lock = ReassemblyTriggeredLock(
            reassembly_triggered_table, region_name="us-east-1"
        )
        assert lock.try_create_triggered("job-create-1") is True
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(
            reassembly_triggered_table
        )
        item = table.get_item(Key={"job_id": "job-create-1"})["Item"]
        assert "triggered_at" in item
        assert "ttl" in item
        assert item["ttl"] == item["triggered_at"] + (90 * 86400)

    def test_try_create_triggered_second_call_returns_false(
        self, reassembly_triggered_table
    ):
        lock = ReassemblyTriggeredLock(
            reassembly_triggered_table, region_name="us-east-1"
        )
        assert lock.try_create_triggered("job-create-2") is True
        assert lock.try_create_triggered("job-create-2") is False


class TestInferenceInvocationsStore:
    """Tests for InferenceInvocationsStore (output_location -> job/segment correlation)."""

    def test_put_and_get(self, inference_invocations_table):
        store = InferenceInvocationsStore(
            inference_invocations_table, region_name="us-east-1"
        )
        output_location = "s3://bucket/sagemaker-async-responses/xyz"
        store.put(
            output_location,
            job_id="job-1",
            segment_index=2,
            total_segments=5,
            output_s3_uri="s3://bucket/jobs/job-1/segments/2.mp4",
        )
        got = store.get(output_location)
        assert got is not None
        assert got["job_id"] == "job-1"
        assert got["segment_index"] == 2
        assert got["total_segments"] == 5
        assert got["output_s3_uri"] == "s3://bucket/jobs/job-1/segments/2.mp4"

    def test_get_missing_returns_none(self, inference_invocations_table):
        store = InferenceInvocationsStore(
            inference_invocations_table, region_name="us-east-1"
        )
        assert store.get("s3://bucket/missing") is None

    def test_delete_removes_item(self, inference_invocations_table):
        store = InferenceInvocationsStore(
            inference_invocations_table, region_name="us-east-1"
        )
        output_location = "s3://bucket/sagemaker-async-responses/abc"
        store.put(output_location, "job-2", 0, 1, "s3://bucket/jobs/job-2/segments/0.mp4")
        assert store.get(output_location) is not None
        store.delete(output_location)
        assert store.get(output_location) is None

    def test_put_sets_ttl(self, inference_invocations_table):
        import time
        store = InferenceInvocationsStore(
            inference_invocations_table, region_name="us-east-1"
        )
        output_location = "s3://bucket/sagemaker-async-responses/ttl"
        before = int(time.time())
        store.put(output_location, "job-3", 1, 3, "s3://out/1.mp4")
        after = int(time.time())
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(
            inference_invocations_table
        )
        item = table.get_item(Key={"output_location": output_location})["Item"]
        assert "ttl" in item
        assert before + 7200 <= item["ttl"] <= after + 7200 + 2
