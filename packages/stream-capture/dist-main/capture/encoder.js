"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.isWebM = isWebM;
exports.webmToMp4 = webmToMp4;
exports.ensureMp4 = ensureMp4;
const child_process_1 = require("child_process");
const os_1 = require("os");
const path_1 = __importDefault(require("path"));
const promises_1 = __importDefault(require("fs/promises"));
/** WebM magic bytes (EBML header) */
const WEBM_MAGIC = Buffer.from([0x1a, 0x45, 0xdf, 0xa3]);
function isWebM(buffer) {
    return buffer.length >= 4 && buffer.subarray(0, 4).equals(WEBM_MAGIC);
}
/**
 * Convert WebM buffer to MP4 (H.264 + AAC) using ffmpeg CLI.
 * Requires ffmpeg on PATH. Returns MP4 buffer or throws.
 */
function webmToMp4(buffer) {
    return new Promise((resolve, reject) => {
        const prefix = path_1.default.join((0, os_1.tmpdir)(), `stream-capture-${process.pid}-${Date.now()}`);
        const inputPath = `${prefix}.webm`;
        const outputPath = `${prefix}.mp4`;
        const cleanup = () => {
            void promises_1.default.unlink(inputPath).catch(() => { });
            void promises_1.default.unlink(outputPath).catch(() => { });
        };
        void promises_1.default
            .writeFile(inputPath, buffer)
            .then(() => {
            const ff = (0, child_process_1.spawn)("ffmpeg", [
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
            ], { stdio: "pipe" });
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
                void promises_1.default
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
async function ensureMp4(buffer) {
    if (!isWebM(buffer))
        return buffer;
    return webmToMp4(buffer);
}
