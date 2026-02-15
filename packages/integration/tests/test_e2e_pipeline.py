"""
End-to-end integration test: create job → upload → chunking → video-worker → reassembly → completed.

Uses moto for AWS resources. Requires ffmpeg to generate a minimal source video.
"""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from stereo_spot_shared import JobStatus, build_segment_key

from media_worker.chunking import process_one_chunking_message
from media_worker.reassembly import process_one_reassembly_message
from reassembly_trigger.handler import process_job_id
from stereo_spot_aws_adapters.env_config import (
    chunking_queue_receiver_from_env,
    chunking_queue_sender_from_env,
    input_bucket_name,
    job_store_from_env,
    object_storage_from_env,
    output_bucket_name,
    reassembly_queue_receiver_from_env,
    reassembly_queue_sender_from_env,
    reassembly_triggered_lock_from_env,
    segment_completion_store_from_env,
    video_worker_queue_receiver_from_env,
    video_worker_queue_sender_from_env,
)
from stereo_spot_web_ui.main import app
from video_worker.runner import process_one_message


def _make_s3_event_body(bucket: str, key: str) -> str:
    return json.dumps({
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                }
            }
        ]
    })


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not available",
)
def test_e2e_pipeline_create_upload_chunking_video_reassembly_completed(
    integration_env: dict[str, str],
    minimal_mp4_path: Path | None,
) -> None:
    """
    Full pipeline: create job via API, upload source, run chunking, run video-worker
    for all segments, simulate reassembly trigger, run reassembly; assert Job completed
    and final.mp4 exists.
    """
    if minimal_mp4_path is None:
        pytest.skip("ffmpeg could not create minimal mp4")

    input_bucket = integration_env["INPUT_BUCKET_NAME"]
    output_bucket = integration_env["OUTPUT_BUCKET_NAME"]
    jobs_table = integration_env["JOBS_TABLE_NAME"]
    segment_completions_table = integration_env["SEGMENT_COMPLETIONS_TABLE_NAME"]
    reassembly_triggered_table = integration_env["REASSEMBLY_TRIGGERED_TABLE_NAME"]
    reassembly_queue_url = integration_env["REASSEMBLY_QUEUE_URL"]

    # 1. Create job via web-ui API
    client = TestClient(app)
    response = client.post("/jobs", data={"mode": "anaglyph"}, follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert "/jobs/" in location
    job_id = location.split("/jobs/")[1].rstrip("/")
    assert job_id

    # 2. Upload source to S3
    storage = object_storage_from_env()
    source_key = f"input/{job_id}/source.mp4"
    source_bytes = minimal_mp4_path.read_bytes()
    storage.upload(input_bucket, source_key, source_bytes)

    # 3. Send chunking message (S3 event shape, same as real S3 → SQS) and process it
    chunking_sender = chunking_queue_sender_from_env()
    chunking_sender.send(_make_s3_event_body(input_bucket, source_key))
    chunking_receiver = chunking_queue_receiver_from_env()
    job_store = job_store_from_env()

    messages = chunking_receiver.receive(max_messages=1)
    assert len(messages) == 1
    msg = messages[0]
    ok = process_one_chunking_message(
        msg.body,
        job_store,
        storage,
        input_bucket,
        segment_duration_sec=1,
    )
    assert ok is True
    chunking_receiver.delete(msg.receipt_handle)

    # 4. Assert chunking complete and get total_segments
    job = job_store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.CHUNKING_COMPLETE
    assert job.total_segments is not None
    total_segments = job.total_segments
    mode = job.mode

    # 5. Send video-worker messages (S3 event shape for each segment) and process each
    video_sender = video_worker_queue_sender_from_env()
    for i in range(total_segments):
        segment_key = build_segment_key(job_id, i, total_segments, mode)
        body = _make_s3_event_body(input_bucket, segment_key)
        video_sender.send(body)

    segment_store = segment_completion_store_from_env()
    video_receiver = video_worker_queue_receiver_from_env()
    processed = 0
    for _ in range(total_segments):
        messages = video_receiver.receive(max_messages=1)
        if not messages:
            break
        msg = messages[0]
        ok = process_one_message(
            msg.body,
            storage,
            segment_store,
            output_bucket,
        )
        if ok:
            video_receiver.delete(msg.receipt_handle)
            processed += 1
    assert processed == total_segments

    # 6. Simulate reassembly trigger Lambda: conditional create ReassemblyTriggered, send to queue
    process_job_id(
        job_id,
        jobs_table,
        segment_completions_table,
        reassembly_triggered_table,
        reassembly_queue_url,
    )

    # 7. Process one reassembly message
    reassembly_receiver = reassembly_queue_receiver_from_env()
    lock = reassembly_triggered_lock_from_env()
    messages = reassembly_receiver.receive(max_messages=1)
    assert len(messages) == 1
    msg = messages[0]
    ok = process_one_reassembly_message(
        msg.body,
        job_store,
        segment_store,
        storage,
        lock,
        output_bucket,
    )
    assert ok is True
    reassembly_receiver.delete(msg.receipt_handle)

    # 8. Assert Job completed and final.mp4 exists
    job = job_store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    final_key = f"jobs/{job_id}/final.mp4"
    assert storage.exists(output_bucket, final_key)
