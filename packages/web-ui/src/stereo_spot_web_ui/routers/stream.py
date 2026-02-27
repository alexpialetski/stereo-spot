"""Stream session and playlist API: create session, end session, HLS playlist."""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..deps import (
    get_input_bucket,
    get_object_storage,
    get_output_bucket,
    get_stream_sessions_store_optional,
    get_templates,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Session ID: allow alphanumeric, hyphen, underscore; reject path traversal
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# HLS segment key pattern: stream_output/{session_id}/seg_NNNNN.mp4
SEG_KEY_PATTERN = re.compile(r"^seg_(\d{5})\.mp4$")

STREAM_CREDENTIALS_DURATION_SEC = 3600  # 1 hour
PLAYLIST_PRESIGN_EXPIRY_SEC = 600  # 10 min
HLS_TARGET_DURATION_SEC = 5
HLS_SEGMENT_DURATION_DEFAULT = 5.0


class CreateStreamSessionRequest(BaseModel):
    """Request body for POST /stream_sessions."""

    mode: str = Field(..., description="Output stereo format: sbs or anaglyph")


class CreateStreamSessionResponse(BaseModel):
    """Response for POST /stream_sessions."""

    session_id: str
    playlist_url: str
    upload: dict[str, Any]


def _validate_session_id(session_id: str) -> None:
    if not session_id or not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")


def _base_url(request: Request) -> str:
    """Base URL for playlist and links (WEB_UI_URL or request)."""
    base = os.environ.get("WEB_UI_URL")
    if base:
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


def _mint_stream_upload_credentials(
    session_id: str,
    input_bucket: str,
    region: str | None,
    duration_seconds: int = STREAM_CREDENTIALS_DURATION_SEC,
) -> dict[str, Any]:
    """Get temporary credentials scoped to stream_input/{session_id}/* (PutObject only)."""
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:AbortMultipartUpload"],
                "Resource": f"arn:aws:s3:::{input_bucket}/stream_input/{session_id}/*",
            }
        ],
    }
    policy_json = json.dumps(policy)
    sts = boto3.client("sts", region_name=region)
    resp = sts.get_federation_token(
        Name=f"stream-{session_id}",
        Policy=policy_json,
        DurationSeconds=duration_seconds,
    )
    creds = resp["Credentials"]
    expires = creds["Expiration"]
    expires_at = expires.strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(expires, "strftime") else str(expires)
    return {
        "access_key_id": creds["AccessKeyId"],
        "secret_access_key": creds["SecretAccessKey"],
        "session_token": creds["SessionToken"],
        "bucket": input_bucket,
        "region": region or "us-east-1",
        "expires_at": expires_at,
    }


@router.post("/stream_sessions", response_model=CreateStreamSessionResponse)
async def create_stream_session(
    request: Request,
    body: CreateStreamSessionRequest,
    input_bucket: str = Depends(get_input_bucket),
    stream_store=Depends(get_stream_sessions_store_optional),
) -> CreateStreamSessionResponse:
    """Create a stream session; returns session_id, playlist_url, and temp upload credentials."""
    mode_val = (body.mode or "sbs").lower()
    if mode_val not in ("sbs", "anaglyph"):
        raise HTTPException(status_code=400, detail="mode must be sbs or anaglyph")
    session_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if stream_store is not None:
        stream_store.put(session_id, now_iso, mode_val, ended_at=None)
    logger.info("stream_sessions create session_id=%s mode=%s", session_id, mode_val)
    region = os.environ.get("AWS_REGION")
    upload = _mint_stream_upload_credentials(session_id, input_bucket, region)
    base = _base_url(request)
    playlist_url = f"{base}/stream/{session_id}/playlist.m3u8"
    return CreateStreamSessionResponse(
        session_id=session_id,
        playlist_url=playlist_url,
        upload=upload,
    )


@router.post("/stream_sessions/{session_id}/end", status_code=204)
async def end_stream_session(
    session_id: str,
    stream_store=Depends(get_stream_sessions_store_optional),
) -> None:
    """Mark stream session as ended (for #EXT-X-ENDLIST in playlist)."""
    _validate_session_id(session_id)
    if stream_store is None:
        return
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        stream_store.set_ended_at(session_id, now_iso)
        logger.info("stream_sessions end session_id=%s", session_id)
    except Exception as e:
        logger.warning("stream_sessions set_ended_at session_id=%s: %s", session_id, e)
        raise HTTPException(status_code=500, detail="Failed to end session")


@router.get("/stream/{session_id}/playlist.m3u8", response_class=PlainTextResponse)
async def get_stream_playlist(
    request: Request,
    session_id: str,
    object_storage=Depends(get_object_storage),
    output_bucket: str = Depends(get_output_bucket),
    stream_store=Depends(get_stream_sessions_store_optional),
) -> PlainTextResponse:
    """Return HLS EVENT playlist for stream session (presigned segment URLs)."""
    _validate_session_id(session_id)
    ended_at = None
    if stream_store is not None:
        session = stream_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        ended_at = session.get("ended_at")
    prefix = f"stream_output/{session_id}/"
    try:
        keys = _list_segment_keys(object_storage, output_bucket, prefix)
        logger.info("stream playlist session_id=%s segments=%s", session_id, len(keys))
    except Exception as e:
        logger.exception("stream playlist list_segments session_id=%s: %s", session_id, e)
        raise HTTPException(status_code=503, detail="Failed to list segments")
    body = _build_playlist(
        object_storage, output_bucket, prefix, keys, add_endlist=ended_at is not None
    )
    return PlainTextResponse(
        content=body,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


def _list_segment_keys(object_storage: Any, bucket: str, prefix: str) -> list[str]:
    """List S3 keys under prefix, filter to seg_NNNNN.mp4, sort lexicographically."""
    all_keys = object_storage.list_object_keys(bucket, prefix)
    keys = []
    for key in all_keys:
        name = key[len(prefix) :] if key.startswith(prefix) else key
        if SEG_KEY_PATTERN.match(name):
            keys.append(key)
    keys.sort()
    return keys


def _build_playlist(
    object_storage: Any,
    bucket: str,
    prefix: str,
    keys: list[str],
    *,
    add_endlist: bool = False,
) -> str:
    """Build M3U8 body with presigned segment URLs."""
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{HLS_TARGET_DURATION_SEC}",
        "#EXT-X-PLAYLIST-TYPE:EVENT",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    for key in keys:
        url = object_storage.presign_download(
            bucket, key, expires_in=PLAYLIST_PRESIGN_EXPIRY_SEC
        )
        lines.append(f"#EXTINF:{HLS_SEGMENT_DURATION_DEFAULT},")
        lines.append(url)
    if add_endlist:
        lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"
