"""Pydantic models for jobs, segments, queue payloads, and API DTOs."""

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class StereoMode(str, Enum):
    """Output stereo format: anaglyph or side-by-side."""

    ANAGLYPH = "anaglyph"
    SBS = "sbs"


class JobStatus(str, Enum):
    """Lifecycle status of a conversion job."""

    CREATED = "created"
    INGESTING = "ingesting"
    CHUNKING_IN_PROGRESS = "chunking_in_progress"
    CHUNKING_COMPLETE = "chunking_complete"
    REASSEMBLING = "reassembling"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class Job(BaseModel):
    """Job record (DynamoDB Jobs table, API)."""

    job_id: str = Field(..., description="Unique job identifier")
    mode: StereoMode = Field(..., description="Output stereo format")
    status: JobStatus = Field(..., description="Current job status")
    created_at: int | None = Field(None, description="Unix timestamp when job was created")
    total_segments: int | None = Field(
        None, description="Number of segments (set when chunking completes)"
    )
    completed_at: int | None = Field(
        None, description="Unix timestamp when job was completed"
    )
    title: str | None = Field(
        None, description="Optional display name (e.g. from upload filename)"
    )
    uploaded_at: int | None = Field(
        None, description="Unix timestamp when upload finished"
    )
    source_file_size_bytes: int | None = Field(
        None, description="Size of uploaded source file in bytes"
    )


# --- Segment key payload (from S3 key parser) and video-worker queue ---

class VideoWorkerPayload(BaseModel):
    """Canonical payload for the video-worker queue (from segment key or S3 event)."""

    job_id: str
    segment_index: int = Field(..., ge=0)
    total_segments: int = Field(..., ge=1)
    segment_s3_uri: str = Field(..., description="s3://bucket/key for the segment")
    mode: StereoMode


# Alias for clarity when parsing segment keys
SegmentKeyPayload = VideoWorkerPayload


class SegmentCompletion(BaseModel):
    """DynamoDB SegmentCompletions record (written by video-worker)."""

    job_id: str
    segment_index: int = Field(..., ge=0)
    output_s3_uri: str = Field(..., description="s3://bucket/key for segment output")
    completed_at: int = Field(..., description="Unix timestamp")
    total_segments: int | None = Field(None, description="Optional; for convenience")


# --- Chunking queue: raw S3 event (bucket, key); job_id from key, mode from DynamoDB ---

class ChunkingPayload(BaseModel):
    """
    Payload for the chunking queue (raw S3 event).

    The chunking worker receives bucket + key from S3 notification, parses job_id
    via parse_input_key(), and fetches mode from the Jobs table in DynamoDB.
    """

    bucket: str
    key: str = Field(..., description="Object key, e.g. input/{job_id}/source.mp4")


# --- Reassembly queue ---

class ReassemblyPayload(BaseModel):
    """Payload for the Reassembly SQS queue (sent by Lambda, consumed by media-worker)."""

    job_id: str


# --- Deletion queue ---

class DeletionPayload(BaseModel):
    """Payload for the Deletion SQS queue (sent by web-ui, consumed by media-worker)."""

    job_id: str


# --- Ingest queue (discriminated union by source_type) ---

class YoutubeIngestPayload(BaseModel):
    """YouTube (or yt-dlp–compatible) URL ingest payload."""

    source_type: Literal["youtube"] = "youtube"
    job_id: str
    source_url: str


# Union of all ingest payload variants; add new source types here.
IngestPayloadUnion = YoutubeIngestPayload
IngestPayload = Annotated[
    IngestPayloadUnion,
    Field(discriminator="source_type"),
]


def parse_ingest_payload(data: dict) -> IngestPayloadUnion | None:
    """Parse dict into ingest payload union (discriminated by source_type). None if invalid."""
    try:
        from pydantic import TypeAdapter

        return TypeAdapter(IngestPayload).validate_python(data)
    except Exception:
        return None


# --- API DTOs ---

class CreateJobRequest(BaseModel):
    """Request body for creating a job (form or JSON)."""

    mode: Literal["anaglyph", "sbs"] = Field(..., description="Output stereo format")


class CreateJobResponse(BaseModel):
    """Response after creating a job: job_id and presigned upload URL."""

    job_id: str
    upload_url: str = Field(..., description="Presigned PUT URL for input/{job_id}/source.mp4")


class JobListItem(BaseModel):
    """Item in the list of completed jobs (for GET /jobs)."""

    job_id: str
    mode: StereoMode
    completed_at: int = Field(..., description="Unix timestamp")
    title: str | None = Field(None, description="Optional display name")
    uploaded_at: int | None = Field(None, description="Unix timestamp when upload finished")
    source_file_size_bytes: int | None = Field(
        None, description="Size of uploaded source file in bytes"
    )


class PresignedPlaybackResponse(BaseModel):
    """Response with presigned GET URL for playback (or redirect target)."""

    playback_url: str = Field(..., description="Presigned GET URL for jobs/{job_id}/final.mp4")


# --- Job events (bridge: stream -> normalized event -> JobEvent for SSE/Web Push) ---


class JobTableChange(BaseModel):
    """Normalized event: job table row changed (DynamoDB NewImage or equivalent)."""

    job_id: str = Field(..., description="Job identifier")
    new_image: dict[str, Any] = Field(..., description="New row image (dict for Job)")


class SegmentCompletionInsert(BaseModel):
    """Normalized event: segment completion row inserted."""

    job_id: str = Field(..., description="Job identifier")
    segment_index: int = Field(..., ge=0, description="Segment index")


class JobEvent(BaseModel):
    """Event sent to job-events queue / consumed by web-ui (SSE + Web Push)."""

    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Job status value (e.g. completed, failed)")
    progress_percent: int = Field(..., ge=0, le=100, description="0-100 progress")
    stage_label: str = Field(..., description="Human-readable stage (e.g. Completed, Failed)")
    title: str | None = Field(None, description="Job title if available")
    completed_at: int | None = Field(None, description="Unix timestamp when completed")


