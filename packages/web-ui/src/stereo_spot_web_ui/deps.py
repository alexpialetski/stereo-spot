"""Dependencies and app state for FastAPI routes."""

from fastapi import Request
from fastapi.templating import Jinja2Templates
from stereo_spot_shared import JobStore, ObjectStorage, SegmentCompletionStore
from stereo_spot_shared.interfaces import OperatorLinksProvider, QueueSender


def get_templates(request: Request) -> Jinja2Templates:
    """Return Jinja2Templates from app state (set in main before including routers)."""
    return request.app.state.templates


def get_job_store(request: Request) -> JobStore:
    """Return JobStore from app state or build from env."""
    store = getattr(request.app.state, "job_store", None)
    if store is not None:
        return store
    from stereo_spot_aws_adapters.env_config import job_store_from_env

    return job_store_from_env()


def get_object_storage(request: Request) -> ObjectStorage:
    """Return ObjectStorage from app state or build from env."""
    storage = getattr(request.app.state, "object_storage", None)
    if storage is not None:
        return storage
    from stereo_spot_aws_adapters.env_config import object_storage_from_env

    return object_storage_from_env()


def get_input_bucket(request: Request) -> str:
    """Return input bucket name from app state or env."""
    name = getattr(request.app.state, "input_bucket_name", None)
    if name is not None:
        return name
    from stereo_spot_aws_adapters.env_config import input_bucket_name

    return input_bucket_name()


def get_output_bucket(request: Request) -> str:
    """Return output bucket name from app state or env."""
    name = getattr(request.app.state, "output_bucket_name", None)
    if name is not None:
        return name
    from stereo_spot_aws_adapters.env_config import output_bucket_name

    return output_bucket_name()


def get_segment_completion_store(request: Request) -> SegmentCompletionStore:
    """Return SegmentCompletionStore from app state or build from env."""
    store = getattr(request.app.state, "segment_completion_store", None)
    if store is not None:
        return store
    from stereo_spot_aws_adapters.env_config import segment_completion_store_from_env

    return segment_completion_store_from_env()


def get_deletion_queue_sender(request: Request) -> QueueSender:
    """Return QueueSender for the deletion queue from app state or build from env."""
    sender = getattr(request.app.state, "deletion_queue_sender", None)
    if sender is not None:
        return sender
    from stereo_spot_aws_adapters.env_config import deletion_queue_sender_from_env

    return deletion_queue_sender_from_env()


def get_operator_links_provider(request: Request) -> OperatorLinksProvider | None:
    """Return OperatorLinksProvider from app state or build from env (e.g. AWS)."""
    provider = getattr(request.app.state, "operator_links_provider", None)
    if provider is not None:
        return provider
    from stereo_spot_aws_adapters.env_config import operator_links_from_env

    return operator_links_from_env()
