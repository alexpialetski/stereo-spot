"""Tests for Pydantic model validation and serialization."""

import pytest
from pydantic import ValidationError

from stereo_spot_shared import (
    ChunkingPayload,
    CreateJobRequest,
    CreateJobResponse,
    DeletionPayload,
    Job,
    JobListItem,
    JobStatus,
    PresignedPlaybackResponse,
    ReassemblyPayload,
    SegmentCompletion,
    StereoMode,
    VideoWorkerPayload,
    YoutubeIngestPayload,
    parse_ingest_payload,
)


class TestJob:
    """Job model validation."""

    def test_valid_minimal(self) -> None:
        j = Job(
            job_id="job-1",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.CREATED,
        )
        assert j.job_id == "job-1"
        assert j.mode == StereoMode.ANAGLYPH
        assert j.status == JobStatus.CREATED
        assert j.created_at is None
        assert j.total_segments is None
        assert j.completed_at is None

    def test_valid_full(self) -> None:
        j = Job(
            job_id="job-2",
            mode=StereoMode.SBS,
            status=JobStatus.COMPLETED,
            created_at=1000,
            total_segments=10,
            completed_at=2000,
        )
        assert j.total_segments == 10
        assert j.completed_at == 2000

    def test_status_deleted(self) -> None:
        j = Job(
            job_id="job-del",
            mode=StereoMode.ANAGLYPH,
            status=JobStatus.DELETED,
        )
        assert j.status == JobStatus.DELETED
        assert j.status.value == "deleted"

    def test_status_ingesting(self) -> None:
        j = Job(
            job_id="job-ing",
            mode=StereoMode.SBS,
            status=JobStatus.INGESTING,
        )
        assert j.status == JobStatus.INGESTING
        assert j.status.value == "ingesting"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Job(
                job_id="job-1",
                mode=StereoMode.ANAGLYPH,
                status="invalid_status",
            )


class TestVideoWorkerPayload:
    """VideoWorkerPayload (segment key payload) validation."""

    def test_valid(self) -> None:
        p = VideoWorkerPayload(
            job_id="job-1",
            segment_index=0,
            total_segments=5,
            segment_s3_uri="s3://bucket/segments/job-1/00000_00005_anaglyph.mp4",
            mode=StereoMode.ANAGLYPH,
        )
        assert p.segment_index == 0
        assert p.total_segments == 5

    def test_invalid_negative_segment_index(self) -> None:
        with pytest.raises(ValidationError):
            VideoWorkerPayload(
                job_id="job-1",
                segment_index=-1,
                total_segments=5,
                segment_s3_uri="s3://b/k",
                mode=StereoMode.SBS,
            )

    def test_invalid_zero_total_segments(self) -> None:
        with pytest.raises(ValidationError):
            VideoWorkerPayload(
                job_id="job-1",
                segment_index=0,
                total_segments=0,
                segment_s3_uri="s3://b/k",
                mode=StereoMode.SBS,
            )


class TestSegmentCompletion:
    """SegmentCompletion model validation."""

    def test_valid(self) -> None:
        s = SegmentCompletion(
            job_id="job-1",
            segment_index=3,
            output_s3_uri="s3://out/jobs/job-1/segments/3.mp4",
            completed_at=12345,
        )
        assert s.total_segments is None
        s2 = SegmentCompletion(
            job_id="job-1",
            segment_index=3,
            output_s3_uri="s3://out/jobs/job-1/segments/3.mp4",
            completed_at=12345,
            total_segments=10,
        )
        assert s2.total_segments == 10


class TestChunkingPayload:
    """ChunkingPayload (raw S3 event) validation."""

    def test_valid(self) -> None:
        c = ChunkingPayload(bucket="in-bucket", key="input/job-1/source.mp4")
        assert c.bucket == "in-bucket"
        assert c.key == "input/job-1/source.mp4"


class TestReassemblyPayload:
    """ReassemblyPayload validation."""

    def test_valid(self) -> None:
        r = ReassemblyPayload(job_id="job-1")
        assert r.job_id == "job-1"


class TestDeletionPayload:
    """DeletionPayload validation."""

    def test_valid(self) -> None:
        d = DeletionPayload(job_id="job-1")
        assert d.job_id == "job-1"


class TestCreateJobRequest:
    """CreateJobRequest API DTO validation."""

    def test_valid_anaglyph(self) -> None:
        req = CreateJobRequest(mode="anaglyph")
        assert req.mode == "anaglyph"

    def test_valid_sbs(self) -> None:
        req = CreateJobRequest(mode="sbs")
        assert req.mode == "sbs"

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateJobRequest(mode="invalid")


class TestCreateJobResponse:
    """CreateJobResponse API DTO validation."""

    def test_valid(self) -> None:
        res = CreateJobResponse(
            job_id="job-1",
            upload_url="https://s3.amazonaws.com/...",
        )
        assert res.job_id == "job-1"
        assert "upload_url" in res.model_dump()


class TestJobListItem:
    """JobListItem API DTO validation."""

    def test_valid(self) -> None:
        item = JobListItem(
            job_id="job-1",
            mode=StereoMode.ANAGLYPH,
            completed_at=12345,
        )
        assert item.job_id == "job-1"
        assert item.completed_at == 12345


class TestPresignedPlaybackResponse:
    """PresignedPlaybackResponse API DTO validation."""

    def test_valid(self) -> None:
        res = PresignedPlaybackResponse(playback_url="https://s3.../final.mp4?signature=...")
        assert "final.mp4" in res.playback_url


class TestSerialization:
    """JSON serialization round-trip for queue/API use."""

    def test_video_worker_payload_round_trip(self) -> None:
        p = VideoWorkerPayload(
            job_id="job-1",
            segment_index=1,
            total_segments=10,
            segment_s3_uri="s3://b/k",
            mode=StereoMode.SBS,
        )
        data = p.model_dump(mode="json")
        p2 = VideoWorkerPayload.model_validate(data)
        assert p2.job_id == p.job_id
        assert p2.mode == p.mode

    def test_reassembly_payload_round_trip(self) -> None:
        r = ReassemblyPayload(job_id="job-xyz")
        data = r.model_dump()
        r2 = ReassemblyPayload.model_validate(data)
        assert r2.job_id == r.job_id

    def test_deletion_payload_round_trip(self) -> None:
        d = DeletionPayload(job_id="job-abc")
        data = d.model_dump()
        d2 = DeletionPayload.model_validate(data)
        assert d2.job_id == d.job_id

    def test_youtube_ingest_payload_round_trip(self) -> None:
        i = YoutubeIngestPayload(
            job_id="job-1",
            source_url="https://www.youtube.com/watch?v=abc",
        )
        data = i.model_dump()
        i2 = YoutubeIngestPayload.model_validate(data)
        assert i2.job_id == i.job_id
        assert i2.source_url == i.source_url
        assert i2.source_type == "youtube"

    def test_parse_ingest_payload_youtube(self) -> None:
        data = {"source_type": "youtube", "job_id": "j", "source_url": "https://x"}
        payload = parse_ingest_payload(data)
        assert payload is not None
        assert isinstance(payload, YoutubeIngestPayload)
        assert payload.job_id == "j"
        assert payload.source_url == "https://x"

    def test_parse_ingest_payload_invalid_returns_none(self) -> None:
        assert parse_ingest_payload({}) is None
        assert parse_ingest_payload({"source_type": "unknown", "job_id": "j"}) is None
