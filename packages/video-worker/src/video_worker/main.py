"""
Entrypoint for the video worker. Wires AWS adapters from env and runs two loops:
inference queue (invoke SageMaker/HTTP/stub) and output-events queue
(SegmentCompletion on SageMaker success only).
"""

import logging
import threading

from stereo_spot_aws_adapters.env_config import (
    inference_invocations_store_from_env,
    job_store_from_env,
    object_storage_from_env,
    output_bucket_name,
    output_events_queue_receiver_from_env,
    reassembly_queue_sender_from_env,
    reassembly_triggered_lock_from_env,
    segment_completion_store_from_env,
    video_worker_queue_receiver_from_env,
)
from stereo_spot_shared import configure_logging

from .config import get_settings
from .inference import run_loop
from .output_events import run_output_events_loop

configure_logging()


def main() -> None:
    logger = logging.getLogger(__name__)
    logger.info(
        "video-worker starting (backend=%s)",
        get_settings().inference_backend,
    )
    storage = object_storage_from_env()
    segment_store = segment_completion_store_from_env()
    job_store = job_store_from_env()
    output_bucket = output_bucket_name()
    inference_receiver = video_worker_queue_receiver_from_env()
    output_events_receiver = output_events_queue_receiver_from_env()
    reassembly_triggered = reassembly_triggered_lock_from_env()
    reassembly_sender = reassembly_queue_sender_from_env()
    invocation_store = inference_invocations_store_from_env()

    # Backpressure: limit in-flight SageMaker invocations to match endpoint instance count.
    settings = get_settings()
    inference_semaphore = (
        threading.Semaphore(settings.inference_max_in_flight)
        if settings.use_sagemaker_backend
        else None
    )

    def run_inference_loop() -> None:
        run_loop(
            inference_receiver,
            storage,
            segment_store,
            output_bucket,
            job_store=job_store,
            invocation_store=invocation_store,
            inference_semaphore=inference_semaphore,
        )

    def run_output_events_loop_thread() -> None:
        run_output_events_loop(
            output_events_receiver,
            segment_store,
            output_bucket,
            job_store=job_store,
            reassembly_triggered=reassembly_triggered,
            reassembly_sender=reassembly_sender,
            invocation_store=invocation_store,
            inference_semaphore=inference_semaphore,
        )

    inference_thread = threading.Thread(target=run_inference_loop, daemon=True)
    output_events_thread = threading.Thread(target=run_output_events_loop_thread, daemon=True)
    inference_thread.start()
    output_events_thread.start()
    inference_thread.join()
    output_events_thread.join()


if __name__ == "__main__":
    main()
