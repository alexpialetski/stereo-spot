"""Pytest fixtures: app with mocked JobStore, ObjectStorage, SegmentCompletionStore."""

import pytest
from fastapi.testclient import TestClient
from stereo_spot_shared import (
    Job,
    JobListItem,
    JobStatus,
    SegmentCompletion,
)

from stereo_spot_web_ui.main import app


@pytest.fixture
def client(app_with_mocks: None) -> TestClient:
    """TestClient for the app (requires app_with_mocks to set app.state)."""
    return TestClient(app)


class MockJobStore:
    """JobStore for tests: in-memory, list_completed returns only completed."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str, *, consistent_read: bool = False) -> Job | None:
        return self._jobs.get(job_id)

    def put(self, job: Job) -> None:
        self._jobs[job.job_id] = job

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        total_segments: int | None = None,
        completed_at: int | None = None,
        title: str | None = None,
        uploaded_at: int | None = None,
        source_file_size_bytes: int | None = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        updates = {}
        if status is not None:
            updates["status"] = JobStatus(status)
        if total_segments is not None:
            updates["total_segments"] = total_segments
        if completed_at is not None:
            updates["completed_at"] = completed_at
        if title is not None:
            updates["title"] = title
        if uploaded_at is not None:
            updates["uploaded_at"] = uploaded_at
        if source_file_size_bytes is not None:
            updates["source_file_size_bytes"] = source_file_size_bytes
        if updates:
            job = job.model_copy(update=updates)
            self._jobs[job_id] = job

    def list_completed(
        self,
        limit: int,
        exclusive_start_key: dict | None = None,
    ) -> tuple[list[JobListItem], dict | None]:
        completed = [
            JobListItem(
                job_id=j.job_id,
                mode=j.mode,
                completed_at=j.completed_at or 0,
                title=j.title,
                uploaded_at=j.uploaded_at,
                source_file_size_bytes=j.source_file_size_bytes,
            )
            for j in self._jobs.values()
            if j.status == JobStatus.COMPLETED and j.completed_at is not None
        ]
        completed.sort(key=lambda x: x.completed_at, reverse=True)
        return completed[:limit], None

    def list_in_progress(self, limit: int = 20) -> list[Job]:
        in_progress_statuses = {
            JobStatus.CREATED,
            JobStatus.CHUNKING_IN_PROGRESS,
            JobStatus.CHUNKING_COMPLETE,
            JobStatus.FAILED,
        }
        items = [
            j for j in self._jobs.values()
            if j.status in in_progress_statuses and j.created_at is not None
        ]
        items.sort(key=lambda j: j.created_at or 0, reverse=True)
        return items[:limit]


class MockObjectStorage:
    """ObjectStorage for tests: presign URLs include bucket/key for assertions."""

    def presign_upload(
        self,
        bucket: str,
        key: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        return f"https://mock-upload/{bucket}/{key}?expires={expires_in}"

    def presign_download(
        self,
        bucket: str,
        key: str,
        *,
        expires_in: int = 3600,
        response_content_disposition: str | None = None,
    ) -> str:
        return f"https://mock-download/{bucket}/{key}?expires={expires_in}"

    def upload(self, bucket: str, key: str, body: bytes) -> None:
        pass

    def upload_file(self, bucket: str, key: str, path: str) -> None:
        pass

    def exists(self, bucket: str, key: str) -> bool:
        return False

    def download(self, bucket: str, key: str) -> bytes:
        return b""

    def delete(self, bucket: str, key: str) -> None:
        pass

    def list_object_keys(self, bucket: str, prefix: str) -> list[str]:
        return []


class MockSegmentCompletionStore:
    """SegmentCompletionStore for tests: in-memory, query_by_job returns list."""

    def __init__(self) -> None:
        self._completions: list[SegmentCompletion] = []

    def put(self, completion: SegmentCompletion) -> None:
        self._completions.append(completion)

    def query_by_job(self, job_id: str) -> list[SegmentCompletion]:
        return [c for c in self._completions if c.job_id == job_id]

    def delete_by_job(self, job_id: str) -> None:
        self._completions = [c for c in self._completions if c.job_id != job_id]


class MockDeletionQueueSender:
    """QueueSender for tests: records sent bodies."""

    def __init__(self) -> None:
        self.sent: list[str | bytes] = []

    def send(self, body: str | bytes) -> None:
        self.sent.append(body)


@pytest.fixture
def mock_deletion_queue_sender() -> MockDeletionQueueSender:
    return MockDeletionQueueSender()


@pytest.fixture
def mock_job_store() -> MockJobStore:
    return MockJobStore()


@pytest.fixture
def mock_object_storage() -> MockObjectStorage:
    return MockObjectStorage()


@pytest.fixture
def mock_segment_completion_store() -> MockSegmentCompletionStore:
    return MockSegmentCompletionStore()


@pytest.fixture
def app_with_mocks(
    mock_job_store: MockJobStore,
    mock_object_storage: MockObjectStorage,
    mock_segment_completion_store: MockSegmentCompletionStore,
    mock_deletion_queue_sender: MockDeletionQueueSender,
) -> None:
    """Set app.state so routes use mocks; bucket names fixed."""
    app.state.job_store = mock_job_store
    app.state.object_storage = mock_object_storage
    app.state.segment_completion_store = mock_segment_completion_store
    app.state.deletion_queue_sender = mock_deletion_queue_sender
    app.state.input_bucket_name = "input-bucket"
    app.state.output_bucket_name = "output-bucket"
