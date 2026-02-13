"""
Entrypoint for the reassembly worker. Wires AWS adapters from env and runs the loop.
"""

from stereo_spot_aws_adapters.env_config import (
    job_store_from_env,
    object_storage_from_env,
    output_bucket_name,
    reassembly_queue_receiver_from_env,
    reassembly_triggered_lock_from_env,
    segment_completion_store_from_env,
)

from .runner import run_loop


def main() -> None:
    job_store = job_store_from_env()
    segment_store = segment_completion_store_from_env()
    storage = object_storage_from_env()
    lock = reassembly_triggered_lock_from_env()
    output_bucket = output_bucket_name()
    receiver = reassembly_queue_receiver_from_env()
    run_loop(
        receiver,
        job_store,
        segment_store,
        storage,
        lock,
        output_bucket,
    )


if __name__ == "__main__":
    main()
