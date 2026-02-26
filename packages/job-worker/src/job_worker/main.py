"""
Entrypoint for the job worker. Wires AWS adapters from env and runs the job-status-events loop.
"""

import logging

from stereo_spot_adapters.env_config import (
    inference_invocations_store_from_env,
    job_status_events_queue_receiver_from_env,
    job_store_from_env,
    output_bucket_name,
    reassembly_queue_sender_from_env,
    reassembly_triggered_lock_from_env,
    segment_completion_store_from_env,
)
from stereo_spot_shared import configure_logging

from .job_status_events import run_job_status_events_loop

configure_logging()


def main() -> None:
    logger = logging.getLogger(__name__)
    logger.info("job-worker starting")
    job_store = job_store_from_env()
    segment_store = segment_completion_store_from_env()
    output_bucket = output_bucket_name()
    receiver = job_status_events_queue_receiver_from_env()
    reassembly_triggered = reassembly_triggered_lock_from_env()
    reassembly_sender = reassembly_queue_sender_from_env()
    invocation_store = inference_invocations_store_from_env()

    run_job_status_events_loop(
        receiver,
        segment_store,
        output_bucket,
        job_store=job_store,
        reassembly_triggered=reassembly_triggered,
        reassembly_sender=reassembly_sender,
        invocation_store=invocation_store,
    )


if __name__ == "__main__":
    main()
