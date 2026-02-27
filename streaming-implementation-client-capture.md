# Streaming implementation plan: Desktop capture app

Detailed implementation plan for the **desktop capture app** (Electron + Node) that captures screen or window via `desktopCapturer`, encodes fixed-length chunks to MP4, and uploads to S3. This document assumes the backend already supports **stream sessions** (create session with **temporary AWS credentials**, end session) as described in the orchestration and playback plans. **Upload auth:** temporary credentials (1 h expiry); no per-chunk or batch URL requests — the client uses one set of credentials for all chunk uploads.

**Stack:** Electron + Node. Capture: Electron `desktopCapturer` (screen/window) and **audio** (system audio and/or mic). No web-ui step required to start a stream — the desktop app creates the session and shows the playlist URL directly. Inference accepts and outputs A/V; no extra backend contract.

---

## 1. User flow and UI/UX

**Recommended: start the stream from the desktop app.** The user never has to copy a “stream id” from the web-ui. One place to start, one place to get the playlist URL.

**Happy path:**

1. User opens the **desktop app** (StereoSpot Stream Capture or similar).
2. **Before starting:** User selects what to capture (e.g. “Entire screen” or “Window: Chrome – YouTube”). Optionally picks 3D format (SBS) and resolution (720p / 1080p) from a simple settings area.
3. User clicks **Start streaming**. The app immediately calls the backend to create a stream session and begins capturing. No stream id to copy or paste.
4. **While streaming:** The app shows a status line (“Streaming… chunk 12”) and, prominently, the **playlist URL** (e.g. `https://your-api.example.com/stream/abc-123/playlist.m3u8`). A **Copy** button and a short instruction (“Paste this URL in PotPlayer → 3D SBS”) let the user open the 3D stream on another monitor or device. The app does **not** launch PotPlayer automatically; user pastes the URL manually.
5. User watches the 2D source on the laptop (e.g. video in browser) and the 3D output in PotPlayer. When done, user clicks **Stop streaming**. The app ends the session and stops capture; the playlist URL remains valid for replay until segments are cleaned up (cleanup policy: see orchestration plan).

**UI/UX in short:**

- **Single-window app:** Source picker + Start/Stop + playlist URL + optional settings. No “enter stream id” field in the main flow.
- **Playlist URL is the main output:** Visible and copyable as soon as streaming starts; user does not need to leave the app or open the web-ui to get it.
- **Optional later:** In the web-ui, a “Streaming” area could list *active* or *recent* sessions (e.g. for multi-device or “resume on another machine”) and show the same playlist URL. That stays secondary; the primary flow is “desktop app → Start → copy URL → PotPlayer.”

**Alternative (not recommended for v1):** “Web-ui first” — user creates a stream session in the browser, copies a stream id, pastes it into the desktop app, then starts capture. This adds steps and context-switching; only consider if you need to reserve or manage sessions from the web (e.g. quotas, approval). For most users, starting from the desktop app is simpler.

---

## 2. Scope and dependencies

| Dependency | Provided by |
|------------|-------------|
| Stream session creation | Backend: `POST /stream_sessions` returns `session_id`, **temporary AWS credentials** (1 h), playlist_url |
| Chunk key convention | `stream_input/{session_id}/chunk_{index:05d}.mp4` (see orchestration plan) |
| End-of-stream signal | Backend: `POST /stream_sessions/{id}/end` or `PATCH .../end` |
| Playlist URL for user | Backend: e.g. `https://{host}/stream/{session_id}/playlist.m3u8` returned in session create |

The capture app depends on the orchestration and playback implementations being in place (or at least the API contracts) so it can call start session, upload to the agreed keys, and call end session. **Chunk index = segment index:** client uploads `chunk_{i}.mp4`; inference writes `seg_{i}.mp4` (same index). Segment/playlist retention and cleanup policy: see orchestration plan.

---

## 3. Phases

### Phase 1: Minimal cross-platform capture (single OS first)

**Goal:** One platform (e.g. Windows) working end-to-end: select source → capture → encode chunks → upload.

**Tasks:**

1. **Project setup**
   - Create a new package for the capture app (e.g. `packages/stream-capture`).
   - **Stack:** Electron + Node. Capture via Electron **`desktopCapturer`** (screen/window list and stream). No FFmpeg device names or native capture addons for v1.
   - Add dependency: S3 upload. Use **temporary credentials** returned at session create (1 h expiry). Client uses AWS SDK (or sigv4) to PUT each chunk to `stream_input/{session_id}/chunk_{i:05d}.mp4`; no per-chunk backend requests.

2. **Session lifecycle (client side)**
   - On "Start streaming": call `POST /stream_sessions` with body e.g. `{ "mode": "sbs" }`. Backend returns `session_id`, `playlist_url`, and **temporary AWS credentials** (access_key_id, secret_access_key, session_token, bucket, region) with **1 hour** expiry. Store these; use them for every chunk upload. No further backend calls for uploads until the user stops. **v1:** No credential refresh; streams longer than 1 hour will fail when credentials expire. Consider a UI warning at ~50 minutes or document max stream length 1 h in scope.
   - Store `session_id`, `playlist_url` (to show user “Open in PotPlayer: …”), and the credentials (or an S3 client constructed from them).
   - On "Stop streaming": call `POST /stream_sessions/{id}/end` (or equivalent). No more uploads after that.

3. **Capture source selection**
   - **Video:** UI: list or dropdown of available sources: "Entire screen", "Window: &lt;title&gt;". Use **Electron `desktopCapturer.getSources({ types: ['screen', 'window'] })`**; user picks one. The chosen source id is passed to `getUserMedia` (with the appropriate `chromeMediaSource`) to obtain the capture stream.
   - **Audio:** Capture system audio (e.g. "what you hear" / loopback) and/or mic. In Electron this is typically via `getDisplayMedia` with `audio: true` for system audio, or `getUserMedia` for mic; support varies by OS. Pass the audio track(s) into the same pipeline as the video so they can be muxed into each chunk.

4. **Chunk capture and encode**
   - Fixed chunk duration: **5 seconds** for v1 (no configurable chunk duration in Phase 1).
   - **Capture → encoder path:** MediaStream from `desktopCapturer` (and audio track(s)) is renderer-bound. Recommended: main process receives stream (or frames + audio) via IPC or pipes it from renderer, then feeds FFmpeg (e.g. FFmpeg CLI with `pipe:0` or named pipe). FFmpeg outputs 5 s MP4 segments with **video + audio** muxed. Alternative: renderer draws MediaStream to canvas and exports frames to main (e.g. via IPC); main writes video + audio to FFmpeg stdin. Avoid MediaRecorder in renderer for v1: it typically outputs WebM, requires stop/start every 5 s for fixed chunks, and re-encoding WebM→MP4 adds latency and CPU.
   - Capture: get a continuous stream of video frames and audio. Buffer both for 5 s, then pass to encoder. Mux into a single MP4 per chunk.
   - Encode: produce MP4 with **H.264 (video) + AAC (audio)** for compatibility. Use **FFmpeg** (CLI or lib) in main process for direct MP4 output (video and audio in one container); or system encoder (e.g. Media Foundation on Windows) outputting MP4 with A/V.
   - Output: in-memory buffer or temp file per chunk. Resolution: e.g. **1280×720** or **1920×1080** (configurable). Match backend/iw3 expectations (no transcoding). Each chunk is one MP4 with both tracks; inference accepts and outputs A/V.

5. **Upload**
   - For chunk index `i`, use the **temporary credentials** from session create to PUT to key `stream_input/{session_id}/chunk_{i:05d}.mp4` (same bucket/region from the create response). Use AWS SDK (e.g. `@aws-sdk/client-s3` in Node) or sigv4-signed PUT. No backend request per chunk.
   - Headers: `Content-Type: video/mp4`. **Ordering:** Upload chunks strictly in order. On final upload failure for chunk N (after 2–3 retries with backoff), do not skip to N+1; stop capture, end session, and show error so segment indices stay contiguous for the playlist. Optionally pipeline: encode chunk N+1 in parallel with upload of chunk N; submit uploads in index order.
   - On success, increment index and repeat for next chunk. On failure, retry with backoff (e.g. 2–3 retries); then show error and stop stream.

6. **UI**
   - **No "stream id" input:** User does not paste a session id; the app creates the session on Start and shows the playlist URL.
   - Start / Stop buttons. While streaming: show "Streaming… chunk N" and, prominently, the **playlist URL** with a **Copy** button and short instruction (e.g. "Paste in PotPlayer → 3D SBS"). Do **not** implement launching PotPlayer from the app; user pastes the URL manually.
   - Optional: settings panel for resolution (720p/1080p), default capture source, **system audio on/off**, and **mic on/off**.

**Deliverable:** Windows (or one OS) app that creates a session, captures a window/screen and audio (system + optional mic), produces 5 s A/V MP4 chunks (H.264 + AAC), uploads to `stream_input/{session_id}/chunk_*.mp4`, and ends the session on stop. User can paste playlist URL into PotPlayer and see 3D stream with audio (once backend and inference are in place).

**Out of scope for now:** Multi-platform (macOS/Linux), Phase 2 robustness (error handling, config persistence), and Phase 3 improvements (region capture, auto-start PotPlayer). Focus on Phase 1 only.

---

## 4. Key technical decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Chunk duration | 5 s | Balances latency (shorter = more overhead) and buffer efficiency; matches orchestration/playback docs. |
| Format | MP4, H.264 + AAC | Matches existing inference input (inference accepts and outputs A/V); no server-side transcode. |
| Audio | AAC, muxed in same MP4 | A/V segments improve player start behavior and UX; inference already outputs audio. |
| Upload auth | **Temporary credentials (1 h)** | One request at session start; client signs each PUT. No per-chunk or batch URL requests; keeps up with playback. v1: no credential refresh; max stream length 1 h. |
| First platform | Windows | Largest user base; good capture APIs (Win32, DX, or Electron). |

---

## 5. Backend API contract (client’s view)

Implement these in the **web-ui** package (orchestration plan). **Auth for v1:** none; session create and end are unauthenticated.

- **`POST /stream_sessions`**  
  Body: `{ "mode": "sbs" }` (optional; default sbs for v1). Client does not send `session_id`; backend generates it (e.g. UUID v4).  
  Response: `session_id`, `playlist_url`, and **temporary AWS credentials** for uploads (1 h expiry). Example shape: `{ "session_id": "...", "playlist_url": "...", "upload": { "access_key_id": "...", "secret_access_key": "...", "session_token": "...", "bucket": "...", "region": "...", "expires_at": "..." } }`. Backend uses STS (e.g. AssumeRole or GetFederationToken) with a policy scoped to `s3:PutObject` on `stream_input/{session_id}/*`. Client uses these credentials to PUT each chunk; no further upload-related requests. Backend must validate `session_id` format (e.g. non-empty, no path traversal) where it is used (end, playlist).

- `POST /stream_sessions/{id}/end`  
  Body: optional `{}`.  
  Response: `204 No Content` or `200 { "status": "ended" }`. Backend marks session ended so playlist can add `#EXT-X-ENDLIST`.

- Playlist URL: `GET /stream/{session_id}/playlist.m3u8` (see playback implementation plan). Returned in session create response as `playlist_url`.

---

## 6. File and package layout (suggestion)

**Electron architecture:** Main process holds session API, S3 upload, and FFmpeg (or encoder). Renderer holds UI and capture source selection. Use preload + contextBridge for safe IPC (e.g. start/stop stream, get playlist URL, optional settings). Capture stream or frames are passed to main via IPC or by piping the stream from renderer into FFmpeg in main (see capture→encoder path).

If the app lives in the monorepo:

```
packages/stream-capture/
  package.json          # Electron or Node app
  src/
    main.ts             # Process lifecycle, menu
    capture/
      source.ts         # Enumerate and select source (desktopCapturer)
      chunker.ts        # Buffer N seconds, produce chunk
      encoder.ts        # Frames → MP4 (FFmpeg or native)
    upload/
      client.ts         # S3 PUT with temporary credentials, retries
    api/
      sessions.ts       # POST start (get credentials), POST end
    ui/
      App.tsx           # Start/Stop, playlist URL, settings
  ffmpeg/               # Optional: bundled FFmpeg binary per platform
```

If standalone repo, same structure; ensure backend API base URL is configurable (env or settings).

---

## 7. Order of implementation

1. Backend: stream session create (with temporary credentials) and end (orchestration plan).
2. Backend: playlist endpoint (playback plan).
3. Capture app Phase 1 (one OS, one source type, fixed 5 s chunks, upload with temporary credentials).
4. **Testing**
   - **Unit:** Session API client (create/end), S3 upload client (retries, key format), chunk index logic.
   - **Contract:** POST /stream_sessions and POST …/end request/response against backend or mock.
   - **Integration:** Start session → capture app uploads 3–5 chunks → end session → user pastes playlist URL in PotPlayer → verify playback.
   - **E2E (optional):** Start from UI, copy URL, minimal playback check (e.g. manual or headless).
