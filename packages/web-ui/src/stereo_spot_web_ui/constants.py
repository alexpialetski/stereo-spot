"""Shared constants for web-ui (key templates, timeouts, paths)."""

from pathlib import Path

# Keys per ARCHITECTURE: input/{job_id}/source.mp4, jobs/{job_id}/final.mp4
INPUT_KEY_TEMPLATE = "input/{job_id}/source.mp4"
OUTPUT_FINAL_KEY_TEMPLATE = "jobs/{job_id}/final.mp4"

# Paths (package dir and static/templates under it)
PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
TEMPLATES_DIR = PACKAGE_DIR / "templates"

# Title: max length for storage and for Content-Disposition filename
TITLE_MAX_LENGTH = 200

# SSE poll interval, keepalive, and max stream duration
PROGRESS_POLL_SEC = 2
PROGRESS_KEEPALIVE_SEC = 30
PROGRESS_STREAM_TIMEOUT_SEC = 600  # 10 min

# ETA cache TTL (seconds)
ETA_CACHE_TTL_SEC = 300

# Presigned URL expiry for playback (M3U, in-page video, download, play redirect)
PLAYBACK_PRESIGN_EXPIRY_SEC = 14400  # 4 hours

# Link to user-facing docs for viewing 3D (PotPlayer / Bino)
DOCS_VIEWING_3D_URL = "https://alexpialetski.github.io/stereo-spot/docs/viewing-3d"

# 3D Linker setup EXE filename (served at GET /setup/windows)
SETUP_EXE_FILENAME = "3d_setup.exe"
