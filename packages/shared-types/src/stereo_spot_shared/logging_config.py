"""Shared logging format and configuration for stereo-spot services."""

import logging

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%dT%H:%M:%SZ"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger for this process. Call once at application startup."""
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATEFMT)
