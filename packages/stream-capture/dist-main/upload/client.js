"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.uploadChunk = uploadChunk;
const client_s3_1 = require("@aws-sdk/client-s3");
const constants_js_1 = require("../constants.js");
function buildKey(sessionId, index) {
    const padded = String(index).padStart(5, "0");
    return `${constants_js_1.CHUNK_KEY_PREFIX}/${sessionId}/chunk_${padded}.mp4`;
}
function createS3Client(creds) {
    return new client_s3_1.S3Client({
        region: creds.region,
        credentials: {
            accessKeyId: creds.access_key_id,
            secretAccessKey: creds.secret_access_key,
            sessionToken: creds.session_token,
        },
    });
}
/**
 * Upload one chunk to stream_input/{sessionId}/chunk_{index:05d}.mp4.
 * Retries with backoff; throws after UPLOAD_RETRIES failures.
 */
async function uploadChunk({ sessionId, index, body, credentials, }) {
    const key = buildKey(sessionId, index);
    const client = createS3Client(credentials);
    const command = new client_s3_1.PutObjectCommand({
        Bucket: credentials.bucket,
        Key: key,
        Body: body,
        ContentType: "video/mp4",
    });
    let lastError = null;
    for (let attempt = 0; attempt <= constants_js_1.UPLOAD_RETRIES; attempt++) {
        try {
            await client.send(command);
            return;
        }
        catch (e) {
            lastError = e instanceof Error ? e : new Error(String(e));
            if (attempt < constants_js_1.UPLOAD_RETRIES) {
                await new Promise((r) => setTimeout(r, constants_js_1.UPLOAD_RETRY_DELAY_MS));
            }
        }
    }
    throw lastError ?? new Error("Upload failed");
}
