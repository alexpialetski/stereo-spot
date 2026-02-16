"""
Entrypoint for the video worker. Wires AWS adapters from env and runs the loop.
"""

import logging

from stereo_spot_aws_adapters.env_config import (
    object_storage_from_env,
    output_bucket_name,
    segment_completion_store_from_env,
    video_worker_queue_receiver_from_env,
)

from .runner import run_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)


def main() -> None:
    logger = logging.getLogger(__name__)
    logger.info("video-worker starting")
    storage = object_storage_from_env()
    segment_store = segment_completion_store_from_env()
    output_bucket = output_bucket_name()
    receiver = video_worker_queue_receiver_from_env()
    run_loop(receiver, storage, segment_store, output_bucket)


if __name__ == "__main__":
    main()
