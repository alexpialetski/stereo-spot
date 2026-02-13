"""
Output object key for segment results. Single place for the convention.

Output bucket key format: jobs/{job_id}/segments/{segment_index}.mp4
"""


def build_output_segment_key(job_id: str, segment_index: int) -> str:
    """
    Build the output object key for a processed segment.

    Format: jobs/{job_id}/segments/{segment_index}.mp4
    """
    return f"jobs/{job_id}/segments/{segment_index}.mp4"
