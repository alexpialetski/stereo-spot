import type {
  CreateStreamSessionRequest,
  CreateStreamSessionResponse,
} from "./types.js";
import { DEFAULT_API_BASE } from "../constants.js";

const getBase = (): string => {
  if (typeof process !== "undefined" && process.env?.STREAM_CAPTURE_API_BASE) {
    return process.env.STREAM_CAPTURE_API_BASE.replace(/\/$/, "");
  }
  return DEFAULT_API_BASE;
};

/**
 * Create a stream session; returns session_id, playlist_url, and temp upload credentials.
 */
export async function createStreamSession(
  body: CreateStreamSessionRequest = {}
): Promise<CreateStreamSessionResponse> {
  const base = getBase();
  const res = await fetch(`${base}/stream_sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: body.mode ?? "sbs" }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`createStreamSession failed: ${res.status} ${text}`);
  }
  return res.json() as Promise<CreateStreamSessionResponse>;
}

/**
 * Mark stream session as ended (for #EXT-X-ENDLIST in playlist).
 */
export async function endStreamSession(sessionId: string): Promise<void> {
  const base = getBase();
  const res = await fetch(`${base}/stream_sessions/${encodeURIComponent(sessionId)}/end`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok && res.status !== 204) {
    const text = await res.text();
    throw new Error(`endStreamSession failed: ${res.status} ${text}`);
  }
}
