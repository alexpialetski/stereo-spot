# Streaming implementation plan: Backend HLS playlist endpoint

Detailed implementation plan for the **backend endpoint that generates the HLS playlist on demand**: list segments from S3, build `.m3u8` with presigned segment URLs, and optionally add `#EXT-X-ENDLIST` when the stream session has ended.

---

## 1. Goals and constraints

- **Single URL for the user:** `https://{host}/stream/{session_id}/playlist.m3u8`. PotPlayer (or any HLS client) uses this URL only; the endpoint returns a playlist that references segment URLs.
- **Segments:** Inference writes to `stream_output/{session_id}/seg_{index:05d}.mp4` (see orchestration plan). Segments are video + audio (e.g. H.264 + AAC). Same codec/resolution per segment for seamless playback.
- **Private bucket:** Output bucket is not public; segment URLs in the playlist must be **presigned GET** URLs (e.g. 5–10 min expiry) so the player can fetch without AWS credentials.
- **Live then VOD-style end (EVENT playlist):** Playlist grows as segments appear (HLS **EVENT** mode) and always includes all segments from index 0. When the session is ended, add `#EXT-X-ENDLIST` so the player stops re-fetching and the playlist behaves like VOD.

---

## 2. Components

| Component | Responsibility |
|-----------|----------------|
| **Web-ui (or playback service)** | HTTP endpoint `GET /stream/{session_id}/playlist.m3u8`. |
| **S3 (output bucket)** | ListObjectsV2 under `stream_output/{session_id}/` to get segment keys. |
| **Stream_sessions store (recommended)** | Track created/ended stream sessions: read `ended_at` for `#EXT-X-ENDLIST` and 404 “session not found/expired”. Dev-only mode can run without it and derive “live” purely from S3. |

No new AWS resources for playback itself; only application code and IAM (web-ui already needs S3 read for other features, or add read for `stream_output/*`).

---

## 3. Phase 1: Playlist endpoint

### 3.1 Route

- **Method and path:** `GET /stream/{session_id}/playlist.m3u8`
- **Path parameter:** `session_id` (string). Validate format (e.g. non-empty, no path traversal).
- **Response:** Body = HLS playlist (text); headers below.
- **Auth (v1):** Typically unauthenticated `GET`. Segments remain protected by presigned URLs. If you later add user auth for stream_sessions, you can gate playlist access in the same way.

### 3.2 Handler logic (step-by-step)

1. **Resolve session (recommended)**
   - If you have a `stream_sessions` table (recommended for production), look up `session_id`. If not found, return 404 (session not found/expired). If found, read `ended_at` (null = live, set = ended).
   - In local/dev you may choose to skip this step and treat “session exists” purely as “S3 prefix has objects”; in that mode you can’t distinguish “never existed” from “cleaned up”.

2. **List segments**
   - Call S3 ListObjectsV2 on the **output** bucket with:
     - `Prefix` = `stream_output/{session_id}/`
     - Optionally `MaxKeys` = 1000 (or higher; streams are finite in practice).
   - Use a paginator or loop on `ListObjectsV2` until `IsTruncated` is false so you see **all** objects for that prefix.
   - From all pages, take `Contents[].Key` and filter to keys matching segment convention: e.g. `seg_*.mp4` (or `seg_*.ts` if you change format later). Ignore other objects (e.g. `playlist.m3u8` if you ever write one there).
   - Sort keys lexicographically so order is `seg_00000.mp4`, `seg_00001.mp4`, …. This works because indices are zero-padded (`{index:05d}`) and start at 0.

3. **Build playlist body**
   - Start with:
     ```
     #EXTM3U
     #EXT-X-VERSION:3
     #EXT-X-TARGETDURATION:5
     #EXT-X-PLAYLIST-TYPE:EVENT
     #EXT-X-MEDIA-SEQUENCE:0
     ```
   - `TARGETDURATION` should be >= max segment duration. Use a constant (e.g. 5) if all chunks are 5 s.
   - `PLAYLIST-TYPE:EVENT` expresses the “live then VOD-style” semantics. `MEDIA-SEQUENCE:0` matches the convention that the first segment index is 0 and that the playlist always includes all segments from the start.
   - For each segment key in order:
     - Generate a **presigned GET URL** for that object. Use AWS SDK (boto3) `generate_presigned_url('get_object', Params={'Bucket': output_bucket, 'Key': key}, ExpiresIn=600)` (10 min). Or 300 (5 min) if you prefer shorter expiry; the player will have already fetched the segment by then.
     - Append:
       ```
       #EXTINF:5.0,
       {presigned_url}
       ```
     - Segment duration: use fixed **5.0** if chunk duration is always 5 s. If you store per-segment duration (e.g. in metadata or DynamoDB), read it here and use that value.
   - If session is **ended** (ended_at is set), append:
     ```
     #EXT-X-ENDLIST
     ```

4. **Response**
   - Status: 200 OK.
   - Headers:
     - `Content-Type: application/vnd.apple.mpegurl` (or `application/mpegurl`; both work for most players).
     - `Cache-Control: no-store` or `max-age=0` so the player doesn’t cache the playlist (it should re-fetch every few seconds for live).
   - Body: the playlist string (UTF-8).

### 3.3 Edge cases

- **No segments yet:** List returns 0 keys. Return 200 with only the header lines (#EXTM3U, VERSION, TARGETDURATION) and no #EXTINF lines. Player will retry and see segments later.
- **Invalid session_id:** If you don’t have a stream_sessions table, you can’t 404 “session not found” from DB; any string is “valid”. Optionally 404 only if list returns 0 keys and session is in a known-ended set; otherwise return empty playlist. Simpler: always list S3; if prefix doesn’t exist, list returns 0 keys → empty playlist.
- **Presigned URL expiry:** Player may hold the playlist for a few seconds then request segments; 5–10 min expiry is enough. If a segment request fails with 403 (expired), the player may retry; next playlist fetch will get fresh presigned URLs.
- **S3 or presign failure:** If ListObjectsV2 or presigning fails for transient reasons (network, 5xx), return 503 (or 500) with a small text body and log the error (including `session_id`). The player will usually retry; do not leak internal error details.
- **Retention / cleanup:** After your retention policy deletes `stream_output/{session_id}/...`, you can 404 the playlist (recommended: “session expired”) even if a `stream_sessions` row still exists, or return an empty playlist with `#EXT-X-ENDLIST`. Pick one behavior and keep it consistent with orchestration docs.

---

## 4. Phase 2: Integration and optional enhancements

### 4.1 Where to implement

- **Recommended:** Add the route in **web-ui** (same app that serves the dashboard and job pages). New router or add to existing: e.g. `routers/stream.py` with `GET /stream/{session_id}/playlist.m3u8`. Web-ui already has AWS env (region, credentials or IAM role); add S3 client for the output bucket if not already present.
- **Alternative:** Separate small “playback” service that only does playlist (and optionally stream session create/end). Use if you want to scale or deploy playlist serving independently; for most cases web-ui is simpler.

### 4.2 IAM

- Web-ui task role must have `s3:ListBucket` on the output bucket (for ListObjectsV2) and `s3:GetObject` on `stream_output/*` (for generating presigned URLs). If the role already has broad S3 read for the output bucket, no change. Otherwise add a policy or extend existing.

### 4.3 Optional: segment duration from metadata

- When the worker or inference writes a segment, it could set S3 object metadata (e.g. `segment_duration: "5.0"`). When building the playlist, use HeadObject or list with metadata to get duration and output `#EXTINF:{duration},` per segment. Improves accuracy if chunk duration varies slightly.

### 4.4 CORS

- If the playlist or segment URLs are ever requested from a browser (e.g. in-page HLS player), set CORS on the response: `Access-Control-Allow-Origin: *` or your front-end origin. For PotPlayer (native app) CORS is not required.

### 4.5 Observability and future scaling

- Log per request: `session_id`, whether session was found in `stream_sessions`, number of segments returned, and whether `#EXT-X-ENDLIST` was added. This makes it easy to debug “player stuck” issues.
- Metrics (optional): e.g. `PlaylistRequests` and `PlaylistSegmentsCount` with dimensions like `live` vs `ended`. Alert if playlists frequently return 0 segments for sessions that should be live.
- For v1, presigning every segment URL on every playlist request is acceptable (typical streams and viewer counts are modest, and S3/SDK can handle the load). If you later add many concurrent viewers or very long sessions, consider:
  - Moving URL protection to CloudFront (signed URLs or signed cookies) and using relative paths in the playlist, or
  - Caching generated playlists or segment URL mappings in memory/Redis for a short TTL.

---

## 5. Implementation order

1. **Web-ui:** Add dependency on boto3 (or use existing) for S3 client and presigned URL.
2. **Web-ui:** Implement `GET /stream/{session_id}/playlist.m3u8`: list S3, filter and sort keys, build m3u8 with presigned URLs, fixed duration 5.0, no #EXT-X-ENDLIST yet. Return correct Content-Type and Cache-Control.
3. **Test:** Upload a few test segment files to `stream_output/test-session/seg_00000.mp4`, etc., then GET playlist and open in PotPlayer or ffplay. Verify segment URLs are valid and playback works.
4. **Optional:** Integrate stream_sessions: read ended_at and add #EXT-X-ENDLIST when set.
5. **Optional:** Per-segment duration from S3 metadata or config.

---

## 6. File and code checklist

| Location | Action |
|----------|--------|
| `web-ui` (e.g. `routers/stream.py`) | New router: `GET /stream/{session_id}/playlist.m3u8` |
| `web-ui` (e.g. `stream/playlist.py`) | Handler: list S3, filter seg_*.mp4, sort, build m3u8, presigned URLs |
| `web-ui` (app wiring) | Register router (e.g. `app.include_router(stream_router, prefix="/stream", tags=["stream"])`) |
| `aws-infra/ecs.tf` (if needed) | Web-ui role: S3 ListBucket + GetObject on output bucket stream_output/* |
| Optional: stream_sessions | Read ended_at in playlist handler; add #EXT-X-ENDLIST |

---

## 7. HLS playlist example (output)

Example body for a session with two segments, not ended:

```
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:5
#EXT-X-PLAYLIST-TYPE:EVENT
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:5.0,
https://output-bucket.s3.region.amazonaws.com/stream_output/sess-abc/seg_00000.mp4?X-Amz-Algorithm=...&X-Amz-Credential=...&X-Amz-Expires=600...
#EXTINF:5.0,
https://output-bucket.s3.region.amazonaws.com/stream_output/sess-abc/seg_00001.mp4?X-Amz-Algorithm=...
```

When session is ended, append:

```
#EXT-X-ENDLIST
```

---

## 8. Dependencies

- **Orchestration:** Segments must be written to `stream_output/{session_id}/seg_*.mp4` by the inference path (see orchestration implementation plan). Playlist only reads; it does not trigger inference.
- **Stream sessions:** `stream_sessions` table and the end-session API (orchestration plan). Required in production for clean 404 vs “live” behavior and for `#EXT-X-ENDLIST`. In local/dev you can run without it and derive “ended” by another rule (e.g. no new segment for N minutes).
