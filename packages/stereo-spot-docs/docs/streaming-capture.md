# Streaming capture app

The **stream-capture** desktop app (Electron) captures screen or window, encodes fixed-length chunks to MP4 (H.264 + AAC), and uploads them to S3 for the **streaming pipeline**. Users get a playlist URL to open in an HLS player (e.g. PotPlayer) for live 3D viewing.

## Overview

- **Package:** `packages/stream-capture`
- **Stack:** Electron + Node (main), React + Vite (renderer)
- **Flow:** User selects capture source → Start streaming → App creates a session via `POST /stream_sessions`, receives temporary AWS credentials and playlist URL → Captures 5 s chunks (MediaRecorder), converts WebM→MP4 with FFmpeg when needed, uploads to `stream_input/{session_id}/chunk_{index:05d}.mp4` → User pastes playlist URL in a player → On Stop, app calls `POST /stream_sessions/{id}/end`

## Building and running

From the repo root:

```bash
nx run stream-capture:build
nx run stream-capture:start
```

Or from `packages/stream-capture`:

```bash
npm run build
npm run start
```

**Requirements:**

- Node 20+
- FFmpeg on PATH (for WebM→MP4 conversion when the system records WebM)
- Backend (web-ui) running with stream session and playlist APIs, and (for full flow) video-worker and inference

**Environment:**

- `STREAM_CAPTURE_API_BASE` — Base URL for the web-ui API (default: `http://localhost:8000`)

## UI

- **Source:** Dropdown of screens and windows (Electron `desktopCapturer`)
- **Start streaming:** Creates session, starts capture and upload
- **Stop capture:** Stops recording; session remains active for replay
- **End session:** Calls session end (playlist can then emit `#EXT-X-ENDLIST`)
- **Playlist URL:** Shown when streaming; copy and paste into PotPlayer (or another HLS player) for 3D SBS playback

## Implementation references

- **Client capture plan:** [`streaming-implementation-client-capture.md`](../../../streaming-implementation-client-capture.md) (repo root)
- **Orchestration:** [`streaming-implementation-orchestration.md`](../../../streaming-implementation-orchestration.md)
- **Playback / HLS:** [`streaming-implementation-playback-hls.md`](../../../streaming-implementation-playback-hls.md)
- **Execution plan:** [`streaming-implementation-plan.md`](../../../streaming-implementation-plan.md)

## Packaging and distribution (Phase 4 item 16)

Target platforms (e.g. Windows, macOS, Linux) and packaging (electron-builder or similar) are not yet implemented. Updates are manual (re-download). To add packaging, introduce electron-builder in `packages/stream-capture` and define build targets per platform; document the chosen update strategy (manual vs auto-update) in this section.

## Feature gating and rollout

Streaming is gated by **STREAMING_ENABLED** on the video-worker (default `false`). Enable in dev/staging first; run a small load test (multiple parallel sessions) before enabling in production. See [AWS runbooks §10 Streaming](/docs/aws/runbooks#10-streaming-live-3d-pipeline).

## Non-goals (this phase)

- **Ultra-low latency** — Chunk duration is 5 s; end-to-end latency is not sub-second.
- **Mobile capture** — Desktop capture only (Electron); no browser or mobile app capture in scope.
- **DRM or access control** — Playlist and segment URLs are presigned; no per-user auth or DRM.
- **Credential refresh** — Temp credentials last 1 h; streams longer than 1 h will fail when they expire.
