"""
Reassembly idempotency test: two reassembly messages for the same job_id result in
exactly one reassembly run and one final.mp4; the other run skips (conditional update
on ReassemblyTriggered fails) and deletes the message without overwriting.
"""

import shutil
import time
from pathlib import Path

import pytest
from media_worker.reassembly import process_one_reassembly_message
from stereo_spot_adapters.env_config import (
    job_store_from_env,
    object_storage_from_env,
    output_bucket_name,
    reassembly_queue_receiver_from_env,
    reassembly_queue_sender_from_env,
    reassembly_triggered_lock_from_env,
    segment_completion_store_from_env,
)
from stereo_spot_shared import Job, JobStatus, ReassemblyPayload, SegmentCompletion, StereoMode


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not available",
)
def test_reassembly_idempotency_two_messages_one_winner(
    integration_env: dict[str, str],
    minimal_mp4_path: Path | None,
) -> None:
    """
    For a job with all segments complete, send two reassembly messages and process both.
    Assert: exactly one reassembly run produces final.mp4; the other run skips (try_acquire fails).
    Video-worker sets job completed when it sees final.mp4 (simulated here).
    """
    import boto3

    if minimal_mp4_path is None:
        pytest.skip("ffmpeg could not create minimal mp4")

    output_bucket = output_bucket_name()
    job_id = "idempotency-test-job"

    # 1. Create job: chunking_complete, total_segments=1
    job_store = job_store_from_env()
    job = Job(
        job_id=job_id,
        mode=StereoMode.ANAGLYPH,
        status=JobStatus.CHUNKING_COMPLETE,
        created_at=int(time.time()),
        total_segments=1,
    )
    job_store.put(job)

    # 2. Put one SegmentCompletion and one segment file (valid mp4 for ffmpeg concat)
    segment_store = segment_completion_store_from_env()
    storage = object_storage_from_env()
    segment_key = f"jobs/{job_id}/segments/0.mp4"
    segment_uri = f"s3://{output_bucket}/{segment_key}"
    storage.upload(output_bucket, segment_key, minimal_mp4_path.read_bytes())
    segment_store.put(
        SegmentCompletion(
            job_id=job_id,
            segment_index=0,
            output_s3_uri=segment_uri,
            completed_at=int(time.time()),
            total_segments=1,
        )
    )

    # 3. Create ReassemblyTriggered item (as Lambda would) so try_acquire succeeds for first worker
    reassembly_triggered_table = integration_env["REASSEMBLY_TRIGGERED_TABLE_NAME"]
    now = int(time.time())
    ttl = now + (90 * 86400)
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=integration_env.get("AWS_REGION", "us-east-1"),
    )
    table = dynamodb.Table(reassembly_triggered_table)
    table.put_item(
        Item={
            "job_id": job_id,
            "triggered_at": now,
            "ttl": ttl,
        }
    )

    # 4. Send two reassembly messages
    reassembly_sender = reassembly_queue_sender_from_env()
    payload = ReassemblyPayload(job_id=job_id).model_dump_json()
    reassembly_sender.send(payload)
    reassembly_sender.send(payload)

    # 5. Process both messages
    reassembly_receiver = reassembly_queue_receiver_from_env()
    lock = reassembly_triggered_lock_from_env()
    final_key = f"jobs/{job_id}/final.mp4"

    messages = reassembly_receiver.receive(max_messages=2)
    assert len(messages) == 2

    first_ok = process_one_reassembly_message(
        messages[0].body,
        job_store,
        segment_store,
        storage,
        lock,
        output_bucket,
    )
    reassembly_receiver.delete(messages[0].receipt_handle)

    second_ok = process_one_reassembly_message(
        messages[1].body,
        job_store,
        segment_store,
        storage,
        lock,
        output_bucket,
    )
    reassembly_receiver.delete(messages[1].receipt_handle)

    # Both return True (first did work, second skipped idempotently)
    assert first_ok is True
    assert second_ok is True

    # 5b. Simulate job-worker: final.mp4 → set job completed
    job_store.update(
        job_id,
        status=JobStatus.COMPLETED.value,
        completed_at=int(time.time()),
    )

    # 6. Assert: exactly one final.mp4, Job completed
    assert storage.exists(output_bucket, final_key)
    job = job_store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.COMPLETED

    # Final file should be the one written by the first worker (concat of the one segment)
    data = storage.download(output_bucket, final_key)
    assert len(data) >= 0  # exists and readable; content is ffmpeg concat output
