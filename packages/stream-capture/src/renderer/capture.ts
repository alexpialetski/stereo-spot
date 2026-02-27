/**
 * Capture screen/window via getUserMedia (with desktopCapturer sourceId),
 * record 5s chunks with MediaRecorder, and call onChunk for each blob.
 * Stops when getStopRequested() returns true (polled periodically).
 */

const CHUNK_MS = 5000;

export function captureWithMediaRecorder(
  sourceId: string,
  onChunk: (blob: Blob) => Promise<void>,
  getStopRequested: () => boolean
): Promise<void> {
  return new Promise((resolve, reject) => {
    const constraints: MediaStreamConstraints = {
      audio: false,
      video: {
        mandatory: {
          chromeMediaSource: "desktop",
          chromeMediaSourceId: sourceId,
        },
      } as MediaTrackConstraints,
    };

    navigator.mediaDevices
      .getUserMedia(constraints)
      .then((stream) => {
        const mimeType = MediaRecorder.isTypeSupported("video/webm; codecs=vp9,opus")
          ? "video/webm; codecs=vp9,opus"
          : MediaRecorder.isTypeSupported("video/webm")
            ? "video/webm"
            : "";
        const recorder = new MediaRecorder(stream, {
          mimeType: mimeType || undefined,
          videoBitsPerSecond: 2_500_000,
          audioBitsPerSecond: 128_000,
        });

        let stopped = false;

        const stop = () => {
          if (stopped) return;
          stopped = true;
          if (recorder.state !== "inactive") recorder.stop();
          stream.getTracks().forEach((t) => t.stop());
          resolve();
        };

        recorder.ondataavailable = async (ev) => {
          if (ev.data.size === 0) return;
          if (getStopRequested()) {
            stop();
            return;
          }
          try {
            await onChunk(ev.data);
          } catch (e) {
            reject(e);
            stop();
          }
        };

        recorder.onerror = (ev) => {
          reject(new Error((ev as ErrorEvent).message ?? "MediaRecorder error"));
          stop();
        };

        recorder.onstop = () => stop();

        recorder.start(CHUNK_MS);

        const checkStopLoop = () => {
          if (stopped) return;
          if (getStopRequested()) {
            stop();
            return;
          }
          setTimeout(checkStopLoop, 400);
        };
        checkStopLoop();
      })
      .catch((e) => reject(e));
  });
}
