"""Output object key for the final reassembled file and reassembly-done sentinel."""

FINAL_KEY_PREFIX = "jobs"
FINAL_KEY_SUFFIX = "final.mp4"
REASSEMBLY_DONE_SENTINEL_SUFFIX = ".reassembly-done"


def build_final_key(job_id: str) -> str:
    """
    Build the output object key for the final reassembled file.

    Format: jobs/{job_id}/final.mp4
    """
    return f"{FINAL_KEY_PREFIX}/{job_id}/{FINAL_KEY_SUFFIX}"


def build_reassembly_done_key(job_id: str) -> str:
    """
    Build the output object key for the reassembly-done sentinel.

    When final.mp4 already exists (idempotent), media-worker writes this so
    video-worker receives an S3 event and sets job to completed.
    Format: jobs/{job_id}/.reassembly-done
    """
    return f"{FINAL_KEY_PREFIX}/{job_id}/{REASSEMBLY_DONE_SENTINEL_SUFFIX}"
