"""Output object key for the final reassembled file."""

FINAL_KEY_PREFIX = "jobs"
FINAL_KEY_SUFFIX = "final.mp4"


def build_final_key(job_id: str) -> str:
    """
    Build the output object key for the final reassembled file.

    Format: jobs/{job_id}/final.mp4
    """
    return f"{FINAL_KEY_PREFIX}/{job_id}/{FINAL_KEY_SUFFIX}"
