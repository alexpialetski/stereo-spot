"""Tests for cloud abstraction interfaces (mock implementations)."""

from stereo_spot_shared import (
    Job,
    JobListItem,
    JobStatus,
    ObjectStorage,
    QueueMessage,
    QueueReceiver,
    QueueSender,
    SegmentCompletion,
    SegmentCompletionStore,
    StereoMode,
)
from stereo_spot_shared.interfaces import JobStore


class MockJobStore:
    """Minimal JobStore implementation for testing."""

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
        if status is not None:
            job = job.model_copy(update={"status": JobStatus(status)})
        if total_segments is not None:
            job = job.model_copy(update={"total_segments": total_segments})
        if completed_at is not None:
            job = job.model_copy(update={"completed_at": completed_at})
        self._jobs[job_id] = job

    def list_completed(
        self,
        limit: int,
        exclusive_start_key: dict | None = None,
    ) -> tuple[list[JobListItem], dict | None]:
        completed = [
            JobListItem(job_id=j.job_id, mode=j.mode, completed_at=j.completed_at or 0)
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
        }
        items = [
            j for j in self._jobs.values()
            if j.status in in_progress_statuses and j.created_at is not None
        ]
        items.sort(key=lambda j: j.created_at or 0, reverse=True)
        return items[:limit]


class MockSegmentCompletionStore:
    """Minimal SegmentCompletionStore implementation for testing."""

    def __init__(self) -> None:
        self._completions: list[SegmentCompletion] = []

    def put(self, completion: SegmentCompletion) -> None:
        self._completions.append(completion)

    def query_by_job(self, job_id: str) -> list[SegmentCompletion]:
        return sorted(
            [c for c in self._completions if c.job_id == job_id],
            key=lambda c: c.segment_index,
        )


class MockQueueSender:
    """Minimal QueueSender implementation for testing."""

    def __init__(self) -> None:
        self.sent: list[str | bytes] = []

    def send(self, body: str | bytes) -> None:
        self.sent.append(body)


class MockQueueReceiver:
    """Minimal QueueReceiver implementation for testing."""

    def __init__(self, messages: list[tuple[str, str | bytes]] | None = None) -> None:
        self._messages = list(messages) if messages else []
        self._receipts: set[str] = set()

    def receive(self, max_messages: int = 1) -> list[QueueMessage]:
        out: list[QueueMessage] = []
        for _ in range(max_messages):
            if not self._messages:
                break
            receipt_handle, body = self._messages.pop(0)
            self._receipts.add(receipt_handle)
            out.append(QueueMessage(receipt_handle=receipt_handle, body=body))
        return out

    def delete(self, receipt_handle: str) -> None:
        self._receipts.discard(receipt_handle)


class MockObjectStorage:
    """Minimal ObjectStorage implementation for testing."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], bytes] = {}

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
        self._objects[(bucket, key)] = body

    def upload_file(self, bucket: str, key: str, path: str) -> None:
        with open(path, "rb") as f:
            self._objects[(bucket, key)] = f.read()

    def exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self._objects

    def download(self, bucket: str, key: str) -> bytes:
        return self._objects.get((bucket, key), b"")


def test_mock_job_store_returns_job() -> None:
    """Mock JobStore satisfies protocol and returns job."""
    store: JobStore = MockJobStore()
    job = Job(
        job_id="job-1",
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CREATED,
    )
    store.put(job)
    assert store.get("job-1") is not None
    assert store.get("job-1").job_id == "job-1"
    assert store.get("missing") is None


def test_mock_segment_completion_store() -> None:
    """Mock SegmentCompletionStore satisfies protocol."""
    store: SegmentCompletionStore = MockSegmentCompletionStore()
    c = SegmentCompletion(
        job_id="job-1",
        segment_index=0,
        output_s3_uri="s3://out/jobs/job-1/segments/0.mp4",
        completed_at=1000,
    )
    store.put(c)
    results = store.query_by_job("job-1")
    assert len(results) == 1
    assert results[0].segment_index == 0


def test_mock_queue_sender_receiver() -> None:
    """Mock QueueSender and QueueReceiver satisfy protocols."""
    sender: QueueSender = MockQueueSender()
    sender.send(b'{"job_id": "job-1"}')
    assert len(sender.sent) == 1  # type: ignore[attr-defined]

    receiver: QueueReceiver = MockQueueReceiver(
        [("rh1", b"msg1"), ("rh2", b"msg2")]
    )
    msgs = receiver.receive(max_messages=2)
    assert len(msgs) == 2
    assert msgs[0].receipt_handle == "rh1"
    assert msgs[0].body == b"msg1"
    receiver.delete("rh1")
    assert receiver.receive() == []


def test_mock_object_storage() -> None:
    """Mock ObjectStorage satisfies protocol."""
    storage: ObjectStorage = MockObjectStorage()
    url_put = storage.presign_upload("bucket", "key")
    assert "mock-upload" in url_put
    url_get = storage.presign_download("bucket", "key")
    assert "mock-download" in url_get
    storage.upload("bucket", "key", b"hello")
    assert storage.download("bucket", "key") == b"hello"
