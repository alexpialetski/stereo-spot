"""Pytest fixtures: app with mocked JobStore and ObjectStorage."""

import pytest
from stereo_spot_shared import Job, JobListItem, JobStatus

from stereo_spot_web_ui.main import app


class MockJobStore:
    """JobStore for tests: in-memory, list_completed returns only completed."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
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
            )
            for j in self._jobs.values()
            if j.status == JobStatus.COMPLETED and j.completed_at is not None
        ]
        completed.sort(key=lambda x: x.completed_at, reverse=True)
        return completed[:limit], None


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


@pytest.fixture
def mock_job_store() -> MockJobStore:
    return MockJobStore()


@pytest.fixture
def mock_object_storage() -> MockObjectStorage:
    return MockObjectStorage()


@pytest.fixture
def app_with_mocks(
    mock_job_store: MockJobStore,
    mock_object_storage: MockObjectStorage,
) -> None:
    """Set app.state so routes use mocks; bucket names fixed."""
    app.state.job_store = mock_job_store
    app.state.object_storage = mock_object_storage
    app.state.input_bucket_name = "input-bucket"
    app.state.output_bucket_name = "output-bucket"
