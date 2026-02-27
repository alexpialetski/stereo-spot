#!/usr/bin/env python3
"""
E2E smoke test for streaming API: create session, fetch playlist, end session.

Requires web-ui running with stream session and playlist endpoints (and optionally
STREAM_SESSIONS_TABLE_NAME for session store). Usage:

  python scripts/stream_e2e.py [--base-url http://localhost:8000]

Exit 0 if all steps succeed; non-zero on failure.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream API E2E smoke test")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Web UI base URL",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Skip SSL certificate verification (insecure; for testing only)",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    open_kw: dict = {"timeout": 10}
    if args.no_verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        open_kw["context"] = ctx

    # 1. Create session
    req = urllib.request.Request(
        f"{base}/stream_sessions",
        data=json.dumps({"mode": "sbs"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, **open_kw) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"POST /stream_sessions failed: {e.code} {e.reason}", file=sys.stderr)
        if e.fp:
            print(e.fp.read().decode(), file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return 1

    session_id = data.get("session_id")
    playlist_url = data.get("playlist_url")
    if not session_id or not playlist_url:
        print("Missing session_id or playlist_url in response", file=sys.stderr)
        return 1
    print(f"Created session_id={session_id}")
    print(f"Playlist URL: {playlist_url}")

    # 2. GET playlist (may be empty or have segments)
    req = urllib.request.Request(f"{base}/stream/{session_id}/playlist.m3u8")
    try:
        with urllib.request.urlopen(req, **open_kw) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("Playlist 404 (session store may be unconfigured)", file=sys.stderr)
            return 1
        print(f"GET playlist failed: {e.code}", file=sys.stderr)
        return 1
    if "#EXTM3U" not in body:
        print("Playlist response missing #EXTM3U", file=sys.stderr)
        return 1
    print("Playlist OK (EVENT type)")

    # 3. End session
    req = urllib.request.Request(
        f"{base}/stream_sessions/{session_id}/end",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, **open_kw) as resp:
            pass
    except urllib.error.HTTPError as e:
        print(f"POST .../end failed: {e.code}", file=sys.stderr)
        return 1

    # 4. GET playlist again; when store is used, should include #EXT-X-ENDLIST
    req = urllib.request.Request(f"{base}/stream/{session_id}/playlist.m3u8")
    try:
        with urllib.request.urlopen(req, **open_kw) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"GET playlist after end failed: {e.code}", file=sys.stderr)
        return 1
    if "#EXT-X-ENDLIST" in body:
        print("Playlist after end includes #EXT-X-ENDLIST")
    else:
        print("(Playlist after end has no #EXT-X-ENDLIST; store may be unconfigured)")

    print("E2E stream API smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
