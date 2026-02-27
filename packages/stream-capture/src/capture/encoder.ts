import { spawn } from "child_process";
import { tmpdir } from "os";
import path from "path";
import fs from "fs/promises";

/** WebM magic bytes (EBML header) */
const WEBM_MAGIC = Buffer.from([0x1a, 0x45, 0xdf, 0xa3]);

export function isWebM(buffer: Buffer): boolean {
  return buffer.length >= 4 && buffer.subarray(0, 4).equals(WEBM_MAGIC);
}

/**
 * Convert WebM buffer to MP4 (H.264 + AAC) using ffmpeg CLI.
 * Requires ffmpeg on PATH. Returns MP4 buffer or throws.
 */
export function webmToMp4(buffer: Buffer): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const prefix = path.join(tmpdir(), `stream-capture-${process.pid}-${Date.now()}`);
    const inputPath = `${prefix}.webm`;
    const outputPath = `${prefix}.mp4`;

    const cleanup = () => {
      void fs.unlink(inputPath).catch(() => {});
      void fs.unlink(outputPath).catch(() => {});
    };

    void fs
      .writeFile(inputPath, buffer)
      .then(() => {
        const ff = spawn(
          "ffmpeg",
          [
            "-y",
            "-i",
            inputPath,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-f",
            "mp4",
            outputPath,
          ],
          { stdio: "pipe" }
        );
        ff.on("error", (err) => {
          cleanup();
          reject(new Error(`FFmpeg not available: ${err.message}. Install ffmpeg for WebM→MP4 conversion.`));
        });
        ff.on("close", (code) => {
          if (code !== 0) {
            cleanup();
            reject(new Error(`FFmpeg exited with code ${code}`));
            return;
          }
          void fs
            .readFile(outputPath)
            .then((out) => {
              cleanup();
              resolve(out);
            })
            .catch((e) => {
              cleanup();
              reject(e);
            });
        });
      })
      .catch(reject);
  });
}

/**
 * Ensure buffer is MP4. If it's WebM, convert with ffmpeg; otherwise return as-is.
 */
export async function ensureMp4(buffer: Buffer): Promise<Buffer> {
  if (!isWebM(buffer)) return buffer;
  return webmToMp4(buffer);
}
