"""
Platform adapter facade: build adapter instances from env by PLATFORM (aws | gcp).

Reads PLATFORM (default "aws") and delegates to stereo_spot_aws_adapters or, when
implemented, gcp adapters. Apps import from this module so implementation choice
lives in one place.
"""

import os

from stereo_spot_shared import NoOpConversionMetricsEmitter, NoOpHfTokenProvider
from stereo_spot_shared.interfaces import ObjectStorage


def _platform() -> str:
    """Return PLATFORM env (aws | gcp), default aws."""
    return (os.environ.get("PLATFORM", "aws") or "aws").strip().lower()


def _require_aws() -> None:
    if _platform() != "aws":
        raise NotImplementedError(
            f"PLATFORM={_platform()!r} is not implemented; only aws is supported. "
            "GCP adapters not yet available."
        )


def job_store_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import job_store_from_env as _f
    return _f()


def segment_completion_store_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import segment_completion_store_from_env as _f
    return _f()


def chunking_queue_sender_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import chunking_queue_sender_from_env as _f
    return _f()


def chunking_queue_receiver_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import chunking_queue_receiver_from_env as _f
    return _f()


def video_worker_queue_sender_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import video_worker_queue_sender_from_env as _f
    return _f()


def video_worker_queue_receiver_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import video_worker_queue_receiver_from_env as _f
    return _f()


def output_events_queue_receiver_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import output_events_queue_receiver_from_env as _f
    return _f()


def job_status_events_queue_receiver_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import job_status_events_queue_receiver_from_env as _f
    return _f()


def segment_output_queue_receiver_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import segment_output_queue_receiver_from_env as _f
    return _f()


def inference_invocations_store_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import inference_invocations_store_from_env as _f
    return _f()


def reassembly_triggered_lock_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import reassembly_triggered_lock_from_env as _f
    return _f()


def reassembly_queue_sender_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import reassembly_queue_sender_from_env as _f
    return _f()


def reassembly_queue_receiver_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import reassembly_queue_receiver_from_env as _f
    return _f()


def deletion_queue_sender_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import deletion_queue_sender_from_env as _f
    return _f()


def deletion_queue_receiver_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import deletion_queue_receiver_from_env as _f
    return _f()


def ingest_queue_sender_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import ingest_queue_sender_from_env as _f
    return _f()


def ingest_queue_sender_from_env_or_none():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import ingest_queue_sender_from_env_or_none as _f
    return _f()


def ingest_queue_receiver_from_env_or_none():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import ingest_queue_receiver_from_env_or_none as _f
    return _f()


def job_events_queue_receiver_from_env_or_none():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import job_events_queue_receiver_from_env_or_none as _f
    return _f()


def ingest_queue_receiver_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import ingest_queue_receiver_from_env as _f
    return _f()


def object_storage_from_env() -> ObjectStorage:
    _require_aws()
    from stereo_spot_aws_adapters.env_config import object_storage_from_env as _f
    return _f()


def input_bucket_name() -> str:
    _require_aws()
    from stereo_spot_aws_adapters.env_config import input_bucket_name as _f
    return _f()


def output_bucket_name() -> str:
    _require_aws()
    from stereo_spot_aws_adapters.env_config import output_bucket_name as _f
    return _f()


def operator_links_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.env_config import operator_links_from_env as _f
    return _f()


def push_subscriptions_store_from_env_or_none():
    _require_aws()
    from stereo_spot_aws_adapters.push_subscriptions import (
        push_subscriptions_store_from_env_or_none as _f,
    )
    return _f()


def job_events_normalizer_from_env():
    _require_aws()
    from stereo_spot_aws_adapters.job_events import job_events_normalizer_from_env as _f
    return _f()


def conversion_metrics_emitter_from_env():
    """Return ConversionMetricsEmitter from METRICS_PROVIDER (aws | gcp | none).
    Default aws. No-op for gcp/none/unknown."""
    provider = (os.environ.get("METRICS_PROVIDER") or "aws").strip().lower()
    if provider == "aws":
        _require_aws()
        from stereo_spot_aws_adapters.env_config import conversion_metrics_emitter_from_env as _f
        return _f()
    return NoOpConversionMetricsEmitter()


def hf_token_provider_from_env():
    """Return HfTokenProvider from PLATFORM (aws | gcp). AWS uses Secrets Manager (HF_TOKEN_ARN)."""
    if _platform() == "aws":
        _require_aws()
        from stereo_spot_aws_adapters.env_config import hf_token_provider_from_env as _f
        return _f()
    return NoOpHfTokenProvider()
