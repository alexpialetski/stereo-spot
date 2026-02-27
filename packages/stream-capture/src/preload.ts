import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("desktopCapturer", {
  getSources: (opts: { types: string[]; thumbnailSize?: { width: number; height: number } }) =>
    ipcRenderer.invoke("get-sources", opts),
});

contextBridge.exposeInMainWorld("streamCapture", {
  createSession: (mode?: string) => ipcRenderer.invoke("create-session", mode),
  endSession: () => ipcRenderer.invoke("end-session"),
  uploadChunk: (buffer: ArrayBuffer) => ipcRenderer.invoke("upload-chunk", buffer),
  getSession: () => ipcRenderer.invoke("get-session"),
  requestStop: () => ipcRenderer.invoke("request-stop"),
  onChunkUploaded: (_cb: (index: number) => void) => {
    // Chunk index is returned from upload-chunk; UI will call getSession after each upload
    // So we don't need an event here; UI can pass a callback to the capture loop
    return () => {};
  },
  streamStarted: () => ipcRenderer.send("stream-started"),
  streamStopped: () => ipcRenderer.send("stream-stopped"),
});
