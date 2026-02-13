"""
Stub inference model: passes through segment bytes unchanged.

Allows the pipeline to run without GPU. Replace with a real model (e.g. StereoCrafter)
via configuration or a swappable interface later.
"""


def process_segment(segment_bytes: bytes) -> bytes:
    """
    Stub "inference": return the input unchanged (copy).

    A real implementation would decode video, run stereo/depth model, encode output.
    """
    return segment_bytes
