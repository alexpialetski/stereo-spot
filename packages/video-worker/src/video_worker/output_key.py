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


def build_output_segment_uri(
    output_bucket: str, job_id: str, segment_index: int
) -> str:
    """Build the full S3 URI for a segment output (s3://bucket/jobs/.../segments/N.mp4)."""
    key = build_output_segment_key(job_id, segment_index)
    return f"s3://{output_bucket}/{key}"
