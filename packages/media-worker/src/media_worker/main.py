"""
Entrypoint for the media worker. Wires AWS adapters from env and runs chunking,
reassembly, deletion, and ingest loops in four threads (one process, four queues).
"""

import base64
import json
import logging
import os
import threading

from stereo_spot_adapters.env_config import (
    chunking_queue_receiver_from_env,
    deletion_queue_receiver_from_env,
    ingest_queue_receiver_from_env_or_none,
    input_bucket_name,
    job_store_from_env,
    object_storage_from_env,
    output_bucket_name,
    reassembly_queue_receiver_from_env,
    reassembly_triggered_lock_from_env,
    segment_completion_store_from_env,
)
from stereo_spot_shared import configure_logging

from .chunking import run_chunking_loop
from .config import get_settings
from .deletion import run_deletion_loop
from .ingest import run_ingest_loop
from .reassembly import run_reassembly_loop

configure_logging()


def _setup_ytdlp_cookies_if_configured() -> None:
    """If YTDLP_COOKIES_SECRET_ARN is set, fetch secret and write to temp file for ingest."""
    secret_arn = os.environ.get("YTDLP_COOKIES_SECRET_ARN")
    if not secret_arn:
        return
    try:
        import boto3

        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=secret_arn)
        data = json.loads(resp["SecretString"])
        raw = base64.b64decode(data["cookies_base64"]).decode("utf-8")
        path = "/tmp/ytdlp_cookies.txt"
        with open(path, "w") as f:
            f.write(raw)
        os.environ["YTDLP_COOKIES_PATH"] = path
        logging.getLogger(__name__).info("yt-dlp cookies loaded from Secrets Manager")
    except Exception as e:
        logging.getLogger(__name__).warning(
            "yt-dlp cookies: failed to load from Secrets Manager: %s", e
        )


def main() -> None:
    logger = logging.getLogger(__name__)
    _setup_ytdlp_cookies_if_configured()
    logger.info(
        "media-worker starting (chunking + reassembly + deletion + ingest); "
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
    ingest_receiver = ingest_queue_receiver_from_env_or_none()

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

    def ingest_thread() -> None:
        if ingest_receiver is not None:
            run_ingest_loop(
                ingest_receiver,
                job_store,
                storage,
                input_bucket,
            )
        else:
            logger.info("ingest loop skipped (INGEST_QUEUE_URL not set)")

    t1 = threading.Thread(target=chunking_thread, name="chunking")
    t2 = threading.Thread(target=reassembly_thread, name="reassembly")
    t3 = threading.Thread(target=deletion_thread, name="deletion")
    t4 = threading.Thread(target=ingest_thread, name="ingest")
    t1.daemon = True
    t2.daemon = True
    t3.daemon = True
    t4.daemon = True
    t1.start()
    t2.start()
    t3.start()
    t4.start()
    t1.join()
    t2.join()
    t3.join()
    t4.join()


if __name__ == "__main__":
    main()
