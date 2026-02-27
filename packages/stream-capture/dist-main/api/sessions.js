"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createStreamSession = createStreamSession;
exports.endStreamSession = endStreamSession;
const constants_js_1 = require("../constants.js");
const getBase = () => {
    if (typeof process !== "undefined" && process.env?.STREAM_CAPTURE_API_BASE) {
        return process.env.STREAM_CAPTURE_API_BASE.replace(/\/$/, "");
    }
    return constants_js_1.DEFAULT_API_BASE;
};
/**
 * Create a stream session; returns session_id, playlist_url, and temp upload credentials.
 */
async function createStreamSession(body = {}) {
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
    return res.json();
}
/**
 * Mark stream session as ended (for #EXT-X-ENDLIST in playlist).
 */
async function endStreamSession(sessionId) {
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
