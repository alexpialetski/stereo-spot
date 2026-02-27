/** Chunk key convention: stream_input/{session_id}/chunk_{index:05d}.mp4 */
export const CHUNK_KEY_PREFIX = "stream_input";
export const CHUNK_KEY_FORMAT = "chunk_{index:05d}.mp4";
export const CHUNK_DURATION_MS = 5000;
export const UPLOAD_RETRIES = 3;
export const UPLOAD_RETRY_DELAY_MS = 2000;
export const DEFAULT_API_BASE = "http://localhost:8000";
