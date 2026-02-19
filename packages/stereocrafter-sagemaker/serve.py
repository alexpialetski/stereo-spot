"""
SageMaker inference server: GET /ping and POST /invocations.

Uses iw3 (nunif) to convert 2D video to stereo SBS or anaglyph.

Request body (JSON): {
  "s3_input_uri": "...",
  "s3_output_uri": "...",
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

import boto3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

NUNIF_ROOT = "/opt/nunif"


def get_s3_client():
    return boto3.client("s3")


def get_cloudwatch_client():
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return boto3.client("cloudwatch", region_name=region) if region else boto3.client("cloudwatch")


def _segment_size_bucket(size_mb: float) -> str:
    """Map segment size (MB) to bucket label for CloudWatch dimension. Must match aws-adapters SEGMENT_SIZE_BUCKETS."""
    if size_mb <= 0:
        return "0-5"
    if size_mb < 5:
        return "0-5"
    if size_mb < 20:
        return "5-20"
    if size_mb < 50:
        return "20-50"
    return "50+"


def put_segment_conversion_metrics(duration_seconds: float, size_bytes: int) -> None:
    """Emit CloudWatch metrics for segment conversion (StereoSpot/Conversion): duration and seconds-per-MB, with Cloud + SegmentSizeBucket dimensions."""
    try:
        namespace = os.environ.get("METRICS_NAMESPACE", "StereoSpot/Conversion")
        cloud_name = os.environ.get("ETA_CLOUD_NAME", "aws")
        size_mb = size_bytes / 1e6
        bucket = _segment_size_bucket(size_mb)
        dimensions = [
            {"Name": "Cloud", "Value": cloud_name},
            {"Name": "SegmentSizeBucket", "Value": bucket},
        ]
        metric_data = [
            {
                "MetricName": "SegmentConversionDurationSeconds",
                "Value": duration_seconds,
                "Unit": "Seconds",
                "Dimensions": dimensions,
            },
        ]
        if size_mb > 0:
            conversion_seconds_per_mb = duration_seconds / size_mb
            metric_data.append(
                {
                    "MetricName": "ConversionSecondsPerMb",
                    "Value": conversion_seconds_per_mb,
                    "Unit": "None",
                    "Dimensions": dimensions,
                }
            )
        get_cloudwatch_client().put_metric_data(
            Namespace=namespace,
            MetricData=metric_data,
        )
    except Exception as e:
        logger.warning("Failed to put CloudWatch metrics: %s", e)


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
            # Recommended for video: scene boundary detection + flicker reduction (iw3.md VDA notes)
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
        # iw3 writes {basename}_LRF_Full_SBS.mp4 or anaglyph-named file into out_dir
        candidates = glob.glob(os.path.join(out_dir, "*.mp4"))
        if not candidates:
            raise FileNotFoundError(f"iw3 produced no .mp4 in {out_dir}")
        result_path = candidates[0]
        if len(candidates) > 1:
            # Prefer _LRF_Full_SBS for sbs, or any for anaglyph
            for p in candidates:
                if "_LRF_Full_SBS" in p and mode == "sbs":
                    result_path = p
                    break
                if mode == "anaglyph" and "_LRF_Full_SBS" not in p:
                    result_path = p
                    break
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
        download_from_s3(s3_input_uri, input_path)
        size_bytes = os.path.getsize(input_path)
        run_iw3_pipeline(
            input_path,
            output_path,
            mode=mode,
            job_id=job_id,
            segment_index=segment_index,
        )
        upload_to_s3(output_path, s3_output_uri)
        duration_seconds = time.perf_counter() - start_wall
        logger.info(
            "job_id=%s segment_index=%s invocations complete duration_seconds=%.2f",
            job_id or "?",
            segment_index or "?",
            duration_seconds,
        )
        put_segment_conversion_metrics(duration_seconds, size_bytes)
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
