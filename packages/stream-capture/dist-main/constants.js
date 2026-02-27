"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEFAULT_API_BASE = exports.UPLOAD_RETRY_DELAY_MS = exports.UPLOAD_RETRIES = exports.CHUNK_DURATION_MS = exports.CHUNK_KEY_FORMAT = exports.CHUNK_KEY_PREFIX = void 0;
/** Chunk key convention: stream_input/{session_id}/chunk_{index:05d}.mp4 */
exports.CHUNK_KEY_PREFIX = "stream_input";
exports.CHUNK_KEY_FORMAT = "chunk_{index:05d}.mp4";
exports.CHUNK_DURATION_MS = 5000;
exports.UPLOAD_RETRIES = 3;
exports.UPLOAD_RETRY_DELAY_MS = 2000;
exports.DEFAULT_API_BASE = "http://localhost:8000";
