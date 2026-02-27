import React, { useCallback, useEffect, useRef, useState } from "react";
import { captureWithMediaRecorder } from "./capture";

type Status = "idle" | "starting" | "streaming" | "stopping" | "error";

export default function App() {
  const [sources, setSources] = useState<{ id: string; name: string; thumbnail: string }[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string>("");
  const [status, setStatus] = useState<Status>("idle");
  const [playlistUrl, setPlaylistUrl] = useState<string>("");
  const [chunkIndex, setChunkIndex] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const stopRequestedRef = useRef(false);

  const loadSources = useCallback(async () => {
    if (!window.desktopCapturer) return;
    const srcs = await window.desktopCapturer.getSources({
      types: ["screen", "window"],
    });
    setSources(srcs);
    if (srcs.length > 0 && !selectedSourceId) {
      setSelectedSourceId(srcs[0].id);
    }
  }, [selectedSourceId]);

  useEffect(() => {
    loadSources();
  }, [loadSources]);

  const startStreaming = useCallback(async () => {
    if (!selectedSourceId || !window.streamCapture) return;
    setError(null);
    stopRequestedRef.current = false;
    setStatus("starting");
    try {
      await window.streamCapture.createSession("sbs");
      const session = await window.streamCapture.getSession();
      if (!session) throw new Error("Session not created");
      setPlaylistUrl(session.playlist_url);
      setStatus("streaming");
      window.streamCapture.streamStarted();

      const onChunk = async (blob: Blob) => {
        const buf = await blob.arrayBuffer();
        await window.streamCapture.uploadChunk(buf);
        const s = await window.streamCapture.getSession();
        if (s) setChunkIndex(s.chunk_index);
      };

      await captureWithMediaRecorder(
        selectedSourceId,
        onChunk,
        () => stopRequestedRef.current
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    } finally {
      window.streamCapture.streamStopped();
      setStatus("idle");
    }
  }, [selectedSourceId]);

  const stopStreaming = useCallback(() => {
    stopRequestedRef.current = true;
    void window.streamCapture?.requestStop();
  }, []);

  const endSession = useCallback(async () => {
    setStatus("stopping");
    try {
      await window.streamCapture?.endSession();
    } finally {
      setPlaylistUrl("");
      setChunkIndex(0);
      setStatus("idle");
    }
  }, []);

  const copyPlaylistUrl = useCallback(() => {
    if (playlistUrl) {
      void navigator.clipboard.writeText(playlistUrl);
    }
  }, [playlistUrl]);

  const isStreaming = status === "streaming" || status === "starting";
  const canStart = status === "idle" && selectedSourceId && sources.length > 0;

  return (
    <div className="app">
      <h1>StereoSpot Stream Capture</h1>

      <section className="section">
        <label className="label">Capture source</label>
        <select
          value={selectedSourceId}
          onChange={(e) => setSelectedSourceId(e.target.value)}
          disabled={isStreaming}
        >
          <option value="">Select source…</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </section>

      <section className="section">
        <div className="buttons">
          <button
            className="primary"
            onClick={startStreaming}
            disabled={!canStart}
          >
            Start streaming
          </button>
          {isStreaming && (
            <button className="danger" onClick={stopStreaming}>
              Stop capture
            </button>
          )}
          {playlistUrl && !isStreaming && (
            <button className="danger" onClick={endSession}>
              End session
            </button>
          )}
        </div>

        {playlistUrl && (
          <>
            <label className="label">Playlist URL (paste in PotPlayer → 3D SBS)</label>
            <div className="playlist-row">
              <input
                type="text"
                className="playlist-url"
                readOnly
                value={playlistUrl}
              />
              <button type="button" className="copy-btn" onClick={copyPlaylistUrl}>
                Copy
              </button>
            </div>
          </>
        )}

        {isStreaming && (
          <p className={`status ${status === "streaming" ? "streaming" : ""}`}>
            Streaming… chunk {chunkIndex}
          </p>
        )}

        {error && <div className="error">{error}</div>}

        {playlistUrl && (
          <p className="hint">
            Paste the URL in PotPlayer (or another HLS player) to view the 3D stream.
          </p>
        )}
      </section>
    </div>
  );
}
