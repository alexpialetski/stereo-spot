import { PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import type { StreamUploadCredentials } from "../api/types.js";
import {
  CHUNK_KEY_PREFIX,
  UPLOAD_RETRIES,
  UPLOAD_RETRY_DELAY_MS,
} from "../constants.js";

function buildKey(sessionId: string, index: number): string {
  const padded = String(index).padStart(5, "0");
  return `${CHUNK_KEY_PREFIX}/${sessionId}/chunk_${padded}.mp4`;
}

function createS3Client(creds: StreamUploadCredentials): S3Client {
  return new S3Client({
    region: creds.region,
    credentials: {
      accessKeyId: creds.access_key_id,
      secretAccessKey: creds.secret_access_key,
      sessionToken: creds.session_token,
    },
  });
}

export interface UploadChunkParams {
  sessionId: string;
  index: number;
  body: Uint8Array | Buffer;
  credentials: StreamUploadCredentials;
}

/**
 * Upload one chunk to stream_input/{sessionId}/chunk_{index:05d}.mp4.
 * Retries with backoff; throws after UPLOAD_RETRIES failures.
 */
export async function uploadChunk({
  sessionId,
  index,
  body,
  credentials,
}: UploadChunkParams): Promise<void> {
  const key = buildKey(sessionId, index);
  const client = createS3Client(credentials);
  const command = new PutObjectCommand({
    Bucket: credentials.bucket,
    Key: key,
    Body: body,
    ContentType: "video/mp4",
  });

  let lastError: Error | null = null;
  for (let attempt = 0; attempt <= UPLOAD_RETRIES; attempt++) {
    try {
      await client.send(command);
      return;
    } catch (e) {
      lastError = e instanceof Error ? e : new Error(String(e));
      if (attempt < UPLOAD_RETRIES) {
        await new Promise((r) => setTimeout(r, UPLOAD_RETRY_DELAY_MS));
      }
    }
  }
  throw lastError ?? new Error("Upload failed");
}
