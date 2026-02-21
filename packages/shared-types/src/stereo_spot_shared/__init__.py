"""Shared types and conventions for the stereo-spot video processing pipeline."""

from .interfaces import (
    ConversionMetricsProvider,
    JobStore,
    ObjectStorage,
    QueueMessage,
    QueueReceiver,
    QueueSender,
    SegmentCompletionStore,
)
from .keys import (
    build_segment_key,
    parse_input_key,
    parse_output_segment_key,
    parse_segment_key,
)
from .models import (
    AnalyticsSnapshot,
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
    SegmentKeyPayload,
    StereoMode,
    VideoWorkerPayload,
)

__version__ = "0.1.0"
__all__ = [
    "AnalyticsSnapshot",
    "ConversionMetricsProvider",
    "JobStore",
    "ObjectStorage",
    "QueueMessage",
    "QueueReceiver",
    "QueueSender",
    "SegmentCompletionStore",
    "build_segment_key",
    "parse_input_key",
    "parse_output_segment_key",
    "parse_segment_key",
    "ChunkingPayload",
    "CreateJobRequest",
    "CreateJobResponse",
    "DeletionPayload",
    "Job",
    "JobListItem",
    "JobStatus",
    "PresignedPlaybackResponse",
    "ReassemblyPayload",
    "SegmentCompletion",
    "SegmentKeyPayload",
    "StereoMode",
    "VideoWorkerPayload",
]
