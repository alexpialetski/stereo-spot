"""
Inference server: GET /ping and POST /invocations.

Uses iw3 (nunif) to convert 2D video to stereo SBS or anaglyph. Storage and metrics
are adapter-based (STORAGE_PROVIDER, METRICS_PROVIDER) for AWS/GCP.

Request body (JSON): {
  "input_uri" | "s3_input_uri": "...",   # s3:// or gs://
  "output_uri" | "s3_output_uri": "...",
  "mode": "anaglyph" | "sbs"  (optional, default "anaglyph")
}
"""

from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

NUNIF_ROOT = "/opt/nunif"


def run_iw3_pipeline(
    input_path: str,
    output_path: str,
    mode: str = "anaglyph",
    *,
    job_id: str | None = None,
    segment_index: str | None = None,
) -> None:
    """
    Run iw3 (nunif): 2D video -> stereo SBS or anaglyph.
    iw3 writes to -o directory as {original_filename}_LRF_Full_SBS.mp4 or anaglyph variant.
    """
    with tempfile.TemporaryDirectory() as out_dir:
        cmd = [
            "python", "-m", "iw3",
            "-i", input_path,
            "-o", out_dir,
            "--scene-detect",
            "--ema-normalize",
        ]
        if mode == "anaglyph":
            cmd.extend([
                "--anaglyph",
                "--convergence", "0.5",
                "--divergence", "2.0",
                "--pix-fmt", "yuv444p",
            ])
        if os.environ.get("IW3_LOW_VRAM") == "1":
            cmd.append("--low-vram")
        logger.info(
            "job_id=%s segment_index=%s Running iw3: %s",
            job_id or "?",
            segment_index or "?",
            " ".join(cmd),
        )
        env = os.environ.copy()
        r = subprocess.run(
            cmd,
            cwd=NUNIF_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if r.returncode != 0:
            err_msg = f"iw3 exited {r.returncode}"
            if r.stderr:
                err_msg += f"; stderr:\n{r.stderr}"
            if r.stdout:
                err_msg += f"; stdout:\n{r.stdout}"
            raise RuntimeError(err_msg)
        candidates = glob.glob(os.path.join(out_dir, "*.mp4"))
        if not candidates:
            raise FileNotFoundError(f"iw3 produced no .mp4 in {out_dir}")
        result_path = candidates[0]
        if len(candidates) > 1:
            for p in candidates:
                if "_LRF_Full_SBS" in p and mode == "sbs":
                    result_path = p
                    break
                if mode == "anaglyph" and "_LRF_Full_SBS" not in p:
                    result_path = p
                    break
        shutil.copy2(result_path, output_path)


def _job_id_segment_from_output_uri(output_uri: str) -> tuple[str | None, str | None]:
    """Extract job_id and segment_index from output_uri (e.g. s3://b/jobs/jid/segments/0.mp4 or gs://...)."""
    try:
        parsed = urlparse(output_uri)
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
    Handle POST /invocations. Body: JSON with input_uri/s3_input_uri, output_uri/s3_output_uri, optional mode.
    Returns (response_body, status_code).
    """
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return json.dumps({"error": str(e)}), 400
    input_uri = data.get("input_uri") or data.get("s3_input_uri")
    output_uri = data.get("output_uri") or data.get("s3_output_uri")
    if not input_uri or not output_uri:
        return json.dumps({"error": "input_uri and output_uri (or s3_input_uri and s3_output_uri) required"}), 400
    mode = data.get("mode", "anaglyph")
    if mode not in ("anaglyph", "sbs"):
        return json.dumps({"error": "mode must be anaglyph or sbs"}), 400

    job_id, segment_index = _job_id_segment_from_output_uri(output_uri)
    start_wall = time.perf_counter()
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
        import storage
        storage.download(input_uri, input_path)
        size_bytes = os.path.getsize(input_path)
        run_iw3_pipeline(
            input_path,
            output_path,
            mode=mode,
            job_id=job_id,
            segment_index=segment_index,
        )
        storage.upload(output_path, output_uri)
        duration_seconds = time.perf_counter() - start_wall
        logger.info(
            "job_id=%s segment_index=%s invocations complete duration_seconds=%.2f",
            job_id or "?",
            segment_index or "?",
            duration_seconds,
        )
        import metrics
        metrics.emit_conversion_metrics(duration_seconds, size_bytes)
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
