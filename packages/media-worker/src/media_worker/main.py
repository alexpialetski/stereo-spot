"""
Entrypoint for the media worker. Wires AWS adapters from env and runs chunking,
reassembly, and deletion loops in three threads (one process, three queues).
"""

import logging
import threading

from stereo_spot_aws_adapters.env_config import (
    chunking_queue_receiver_from_env,
    deletion_queue_receiver_from_env,
    input_bucket_name,
    job_store_from_env,
    object_storage_from_env,
    output_bucket_name,
    reassembly_queue_receiver_from_env,
    reassembly_triggered_lock_from_env,
    segment_completion_store_from_env,
)

from .chunking import run_chunking_loop
from .config import get_settings
from .deletion import run_deletion_loop
from .reassembly import run_reassembly_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)


def main() -> None:
    logger = logging.getLogger(__name__)
    logger.info(
        "media-worker starting (chunking + reassembly + deletion); "
        "input_bucket=%s output_bucket=%s",
        input_bucket_name(),
        output_bucket_name(),
    )
    job_store = job_store_from_env()
    storage = object_storage_from_env()
    input_bucket = input_bucket_name()
    output_bucket = output_bucket_name()
    segment_store = segment_completion_store_from_env()
    lock = reassembly_triggered_lock_from_env()
    chunking_receiver = chunking_queue_receiver_from_env()
    reassembly_receiver = reassembly_queue_receiver_from_env()
    deletion_receiver = deletion_queue_receiver_from_env()

    settings = get_settings()

    def chunking_thread() -> None:
        run_chunking_loop(
            chunking_receiver,
            job_store,
            storage,
            input_bucket,
            segment_duration_sec=settings.chunk_segment_duration_sec,
        )

    def reassembly_thread() -> None:
        run_reassembly_loop(
            reassembly_receiver,
            job_store,
            segment_store,
            storage,
            lock,
            output_bucket,
        )

    def deletion_thread() -> None:
        run_deletion_loop(
            deletion_receiver,
            job_store,
            segment_store,
            storage,
            lock,
            input_bucket,
            output_bucket,
        )

    t1 = threading.Thread(target=chunking_thread, name="chunking")
    t2 = threading.Thread(target=reassembly_thread, name="reassembly")
    t3 = threading.Thread(target=deletion_thread, name="deletion")
    t1.daemon = True
    t2.daemon = True
    t3.daemon = True
    t1.start()
    t2.start()
    t3.start()
    t1.join()
    t2.join()
    t3.join()


if __name__ == "__main__":
    main()
