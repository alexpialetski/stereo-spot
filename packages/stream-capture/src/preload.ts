import { contextBridge, ipcRenderer } from "electron";
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { desktopCapturer } = require("electron");

contextBridge.exposeInMainWorld("desktopCapturer", {
  getSources: async (opts: { types: string[] }) => {
    const srcs = await desktopCapturer.getSources(opts);
    return srcs.map((s: { id: string; name: string; thumbnail: { toDataURL: () => string } }) => ({
      id: s.id,
      name: s.name,
      thumbnail: s.thumbnail?.toDataURL() ?? "",
    }));
  },
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
