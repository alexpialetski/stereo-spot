"""Tests for serve: _job_id_segment_from_output_uri and invocations_handler validation."""

from __future__ import annotations

import json
from unittest.mock import patch

import serve


def test_job_id_segment_from_output_uri_s3() -> None:
    assert serve._job_id_segment_from_output_uri("s3://b/jobs/job-123/segments/0.mp4") == ("job-123", "0")
    assert serve._job_id_segment_from_output_uri("s3://bucket/jobs/abc/segments/42.mp4") == ("abc", "42")


def test_job_id_segment_from_output_uri_gs() -> None:
    assert serve._job_id_segment_from_output_uri("gs://b/jobs/jid/segments/1.mp4") == ("jid", "1")


def test_job_id_segment_from_output_uri_invalid_returns_none() -> None:
    assert serve._job_id_segment_from_output_uri("s3://b/other/path") == (None, None)
    assert serve._job_id_segment_from_output_uri("") == (None, None)


def test_invocations_handler_invalid_json_400() -> None:
    body = b"not json"
    resp, status = serve.invocations_handler(body)
    assert status == 400
    data = json.loads(resp)
    assert "error" in data


def test_invocations_handler_missing_input_uri_400() -> None:
    body = json.dumps({"s3_output_uri": "s3://b/out"}).encode()
    resp, status = serve.invocations_handler(body)
    assert status == 400
    data = json.loads(resp)
    assert "input_uri" in data["error"] or "required" in data["error"]


def test_invocations_handler_missing_output_uri_400() -> None:
    body = json.dumps({"s3_input_uri": "s3://b/in"}).encode()
    resp, status = serve.invocations_handler(body)
    assert status == 400
    data = json.loads(resp)
    assert "output_uri" in data["error"] or "required" in data["error"]


def test_invocations_handler_invalid_mode_400() -> None:
    body = json.dumps({
        "s3_input_uri": "s3://b/in",
        "s3_output_uri": "s3://b/out",
        "mode": "invalid",
    }).encode()
    resp, status = serve.invocations_handler(body)
    assert status == 400
    data = json.loads(resp)
    assert "mode" in data["error"]


def _write_one_byte(uri: str, path: str) -> None:
    with open(path, "wb") as f:
        f.write(b"x")


def test_invocations_handler_accepts_input_uri_output_uri() -> None:
    body = json.dumps({
        "input_uri": "s3://b/in",
        "output_uri": "s3://b/out",
    }).encode()
    with patch("storage.download", side_effect=_write_one_byte):
        with patch("storage.upload"):
            with patch("serve.run_iw3_pipeline"):
                with patch("metrics.emit_conversion_metrics") as mock_metrics:
                    resp, status = serve.invocations_handler(body)
    assert status == 200
    assert json.loads(resp) == {"status": "ok"}
    mock_metrics.assert_called_once()


def test_invocations_handler_success_with_s3_uris() -> None:
    body = json.dumps({
        "s3_input_uri": "s3://bucket/in.mp4",
        "s3_output_uri": "s3://bucket/out.mp4",
    }).encode()
    with patch("storage.download", side_effect=_write_one_byte):
        with patch("storage.upload"):
            with patch("serve.run_iw3_pipeline"):
                with patch("metrics.emit_conversion_metrics"):
                    resp, status = serve.invocations_handler(body)
    assert status == 200
    assert json.loads(resp) == {"status": "ok"}
