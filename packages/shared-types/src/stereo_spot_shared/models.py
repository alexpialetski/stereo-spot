"""Pydantic models for jobs, segments, queue payloads, and API DTOs."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class StereoMode(str, Enum):
    """Output stereo format: anaglyph or side-by-side."""

    ANAGLYPH = "anaglyph"
    SBS = "sbs"


class JobStatus(str, Enum):
    """Lifecycle status of a conversion job."""

    CREATED = "created"
    CHUNKING_IN_PROGRESS = "chunking_in_progress"
    CHUNKING_COMPLETE = "chunking_complete"
    COMPLETED = "completed"


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


class PresignedPlaybackResponse(BaseModel):
    """Response with presigned GET URL for playback (or redirect target)."""

    playback_url: str = Field(..., description="Presigned GET URL for jobs/{job_id}/final.mp4")
