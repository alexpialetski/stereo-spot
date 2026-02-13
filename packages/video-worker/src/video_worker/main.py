"""
Entrypoint for the video worker. Wires AWS adapters from env and runs the loop.
"""

from stereo_spot_aws_adapters.env_config import (
    object_storage_from_env,
    output_bucket_name,
    segment_completion_store_from_env,
    video_worker_queue_receiver_from_env,
)

from .runner import run_loop


def main() -> None:
    storage = object_storage_from_env()
    segment_store = segment_completion_store_from_env()
    output_bucket = output_bucket_name()
    receiver = video_worker_queue_receiver_from_env()
    run_loop(receiver, storage, segment_store, output_bucket)


if __name__ == "__main__":
    main()
