# StereoSpot Stream Capture

Electron desktop app for live streaming: capture screen or window, encode 5 s MP4 chunks (H.264 + AAC), and upload to S3 for the streaming pipeline. Users get a playlist URL to open in an HLS player (e.g. PotPlayer) for 3D SBS playback.

## Build and run

```bash
npm install
npm run build
npm run start
```

Or from repo root: `nx run stream-capture:build` and `nx run stream-capture:start`.

## Requirements

- Node 20+
- **FFmpeg** on PATH (used when the system records WebM; converts to MP4 for upload)
- Backend (web-ui) with stream session and playlist APIs

## Config

- `STREAM_CAPTURE_API_BASE` — Web UI API base URL (default: `http://localhost:8000`)

## Docs

See [streaming-capture](../../stereo-spot-docs/docs/streaming-capture.md) in `packages/stereo-spot-docs` and the implementation plans in the repo root (`streaming-implementation-*.md`).
