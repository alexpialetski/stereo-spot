"""
SageMaker inference server: GET /ping and POST /invocations.

Request body (JSON): {
  "s3_input_uri": "...",
  "s3_output_uri": "...",
  "mode": "anaglyph" | "sbs"  (optional, default "anaglyph")
}
The handler reads the segment from S3, runs the StereoCrafter two-stage pipeline
(depth splatting -> inpainting), and writes the result in the requested format
to s3_output_uri.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

import boto3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

STEREOCRAFTER_ROOT = "/opt/stereocrafter"
WEIGHTS_DIR = os.environ.get("WEIGHTS_DIR", "/opt/ml/model/weights")


def get_s3_client():
    return boto3.client("s3")


def download_from_s3(s3_uri: str, path: str) -> None:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    get_s3_client().download_file(bucket, key, path)


def upload_to_s3(path: str, s3_uri: str) -> None:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    get_s3_client().upload_file(path, bucket, key)


def run_stereocrafter_pipeline(
    input_path: str, output_path: str, mode: str = "anaglyph"
) -> None:
    """
    Run the two-stage StereoCrafter pipeline:
    1. depth_splatting_inference.py (DepthCrafter + SVD) -> splatting result
    2. inpainting_inference.py (StereoCrafter + SVD) -> SBS + anaglyph, select by mode
    """
    depthcrafter = os.path.join(WEIGHTS_DIR, "depthcrafter")
    svd = os.path.join(WEIGHTS_DIR, "stable-video-diffusion-img2vid-xt-1-1")
    stereocrafter = os.path.join(WEIGHTS_DIR, "stereocrafter")

    if not all(os.path.isdir(d) for d in (depthcrafter, svd, stereocrafter)):
        raise FileNotFoundError(
            f"Weights not found. Ensure HF_TOKEN_ARN is set and download_weights ran. "
            f"Expected: {depthcrafter}, {svd}, {stereocrafter}"
        )

    env = os.environ.copy()
    env["PYTHONPATH"] = STEREOCRAFTER_ROOT

    with tempfile.TemporaryDirectory() as tmpdir:
        splatting_path = os.path.join(tmpdir, "segment_splatting_results.mp4")
        inpainting_dir = tmpdir

        # Stage 1: depth splatting
        cmd1 = [
            "python",
            os.path.join(STEREOCRAFTER_ROOT, "depth_splatting_inference.py"),
            "--input_video_path", input_path,
            "--output_video_path", splatting_path,
            "--unet_path", depthcrafter,
            "--pre_trained_path", depthcrafter,
        ]
        logger.info("Running depth splatting: %s", " ".join(cmd1))
        subprocess.run(cmd1, env=env, cwd=STEREOCRAFTER_ROOT, check=True)

        # Stage 2: inpainting (produces _sbs.mp4 and _anaglyph.mp4)
        cmd2 = [
            "python",
            os.path.join(STEREOCRAFTER_ROOT, "inpainting_inference.py"),
            "--pre_trained_path", svd,
            "--unet_path", stereocrafter,
            "--input_video_path", splatting_path,
            "--save_dir", inpainting_dir,
        ]
        logger.info("Running inpainting: %s", " ".join(cmd2))
        subprocess.run(cmd2, env=env, cwd=STEREOCRAFTER_ROOT, check=True)

        # Select output by mode: segment_splatting_results_inpainting_results_sbs.mp4 | _anaglyph.mp4
        base_name = "segment_splatting_results_inpainting_results"
        suffix = "_sbs.mp4" if mode == "sbs" else "_anaglyph.mp4"
        result_path = os.path.join(inpainting_dir, base_name + suffix)
        if not os.path.isfile(result_path):
            raise FileNotFoundError(f"Inpainting did not produce {result_path}")
        shutil.copy2(result_path, output_path)


def _job_id_segment_from_output_uri(s3_output_uri: str) -> tuple[str | None, str | None]:
    """Extract job_id and segment_index from s3_output_uri (e.g. s3://b/jobs/jid/segments/0.mp4)."""
    try:
        parsed = urlparse(s3_output_uri)
        key = parsed.path.lstrip("/")
        parts = key.split("/")
        if len(parts) >= 4 and parts[0] == "jobs" and parts[2] == "segments":
            segment_part = parts[3]
            segment_index = segment_part.replace(".mp4", "") if segment_part.endswith(".mp4") else segment_part
            return parts[1], segment_index
    except Exception:
        pass
    return None, None


def invocations_handler(body: bytes) -> tuple[str, int]:
    """
    Handle POST /invocations. Body: JSON with s3_input_uri, s3_output_uri, and optional mode.
    Returns (response_body, status_code).
    """
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return json.dumps({"error": str(e)}), 400
    s3_input_uri = data.get("s3_input_uri")
    s3_output_uri = data.get("s3_output_uri")
    if not s3_input_uri or not s3_output_uri:
        return json.dumps({"error": "s3_input_uri and s3_output_uri required"}), 400
    mode = data.get("mode", "anaglyph")
    if mode not in ("anaglyph", "sbs"):
        return json.dumps({"error": "mode must be anaglyph or sbs"}), 400

    job_id, segment_index = _job_id_segment_from_output_uri(s3_output_uri)
    logger.info(
        "job_id=%s segment_index=%s mode=%s invocations start",
        job_id or "?",
        segment_index or "?",
        mode,
    )
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
        input_path = tmp_in.name
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_out:
        output_path = tmp_out.name
    try:
        download_from_s3(s3_input_uri, input_path)
        run_stereocrafter_pipeline(input_path, output_path, mode=mode)
        upload_to_s3(output_path, s3_output_uri)
        logger.info("job_id=%s segment_index=%s invocations complete", job_id or "?", segment_index or "?")
        return json.dumps({"status": "ok"}), 200
    except Exception as e:
        logger.exception("job_id=%s segment_index=%s invocations failed: %s", job_id or "?", segment_index or "?", e)
        return json.dumps({"error": str(e)}), 500
    finally:
        for p in (input_path, output_path):
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


# Gunicorn/WSGI entrypoint
def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "")
    path = environ.get("PATH_INFO", "")
    if method == "GET" and path.rstrip("/") == "/ping":
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"OK"]
    if method == "POST" and path.rstrip("/") == "/invocations":
        try:
            content_length = int(environ.get("CONTENT_LENGTH", 0))
            body = environ["wsgi.input"].read(content_length) if content_length else b""
        except (ValueError, KeyError):
            body = b""
        response_body, status_code = invocations_handler(body)
        start_response(f"{status_code} OK", [("Content-Type", "application/json")])
        return [response_body.encode("utf-8")]
    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"Not Found"]
