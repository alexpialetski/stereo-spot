"""
Entrypoint for the video worker. Wires AWS adapters from env and runs two loops:
inference queue (invoke SageMaker/HTTP/stub) and segment-output queue (write SegmentCompletion).
"""

import logging
import threading

from stereo_spot_aws_adapters.env_config import (
    job_store_from_env,
    object_storage_from_env,
    output_bucket_name,
    reassembly_queue_sender_from_env,
    reassembly_triggered_lock_from_env,
    segment_completion_store_from_env,
    segment_output_queue_receiver_from_env,
    video_worker_queue_receiver_from_env,
)

from .inference import run_loop
from .segment_output import run_segment_output_loop

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
    job_store = job_store_from_env()
    output_bucket = output_bucket_name()
    inference_receiver = video_worker_queue_receiver_from_env()
    segment_output_receiver = segment_output_queue_receiver_from_env()
    reassembly_triggered = reassembly_triggered_lock_from_env()
    reassembly_sender = reassembly_queue_sender_from_env()

    def run_inference_loop() -> None:
        run_loop(
            inference_receiver,
            storage,
            segment_store,
            output_bucket,
            job_store=job_store,
        )

    def run_segment_output_loop_thread() -> None:
        run_segment_output_loop(
            segment_output_receiver,
            segment_store,
            output_bucket,
            job_store=job_store,
            reassembly_triggered=reassembly_triggered,
            reassembly_sender=reassembly_sender,
        )

    inference_thread = threading.Thread(target=run_inference_loop, daemon=True)
    segment_output_thread = threading.Thread(target=run_segment_output_loop_thread, daemon=True)
    inference_thread.start()
    segment_output_thread.start()
    inference_thread.join()
    segment_output_thread.join()


if __name__ == "__main__":
    main()
