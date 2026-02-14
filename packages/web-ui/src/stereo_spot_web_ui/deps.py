"""Dependencies and app state for FastAPI routes."""

from fastapi import Request
from stereo_spot_shared import JobStore, ObjectStorage


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
