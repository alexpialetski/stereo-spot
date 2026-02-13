"""
Entrypoint for the chunking worker. Wires AWS adapters from env and runs the loop.
"""

import os

from stereo_spot_aws_adapters.env_config import (
    chunking_queue_receiver_from_env,
    input_bucket_name,
    job_store_from_env,
    object_storage_from_env,
)

from .runner import run_loop

SEGMENT_DURATION_SEC = int(os.environ.get("CHUNK_SEGMENT_DURATION_SEC", "300"))


def main() -> None:
    job_store = job_store_from_env()
    storage = object_storage_from_env()
    input_bucket = input_bucket_name()
    receiver = chunking_queue_receiver_from_env()
    run_loop(
        receiver,
        job_store,
        storage,
        input_bucket,
        segment_duration_sec=SEGMENT_DURATION_SEC,
    )


if __name__ == "__main__":
    main()
