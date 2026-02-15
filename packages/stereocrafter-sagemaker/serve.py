"""
SageMaker inference server: GET /ping and POST /invocations.

Request body (JSON): {"s3_input_uri": "...", "s3_output_uri": "..."}.
The handler reads the segment from S3, runs inference (StereoCrafter two-stage pipeline),
and writes the result to s3_output_uri.

For production: replace run_inference_stub() with the real StereoCrafter pipeline
(depth_splatting_inference.py then inpainting_inference.py). Weights are expected
under /opt/ml/model/weights (downloaded at startup from Hugging Face when HF_TOKEN_ARN is set).
"""

from __future__ import annotations

import json
import os
import tempfile
from urllib.parse import urlparse

import boto3

app = None  # Set by gunicorn or Flask


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


def run_inference_stub(input_path: str, output_path: str) -> None:
    """
    Stub: copy input to output. Replace with StereoCrafter two-stage pipeline:
    1. depth_splatting_inference.py (DepthCrafter + SVD) -> splatting result
    2. inpainting_inference.py (StereoCrafter + SVD) -> final stereo (SBS/anaglyph)
    """
    with open(input_path, "rb") as f:
        data = f.read()
    with open(output_path, "wb") as f:
        f.write(data)


def invocations_handler(body: bytes) -> tuple[str, int]:
    """
    Handle POST /invocations. Body: JSON with s3_input_uri and s3_output_uri.
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
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
        input_path = tmp_in.name
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_out:
        output_path = tmp_out.name
    try:
        download_from_s3(s3_input_uri, input_path)
        run_inference_stub(input_path, output_path)
        upload_to_s3(output_path, s3_output_uri)
        return json.dumps({"status": "ok"}), 200
    except Exception as e:
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
