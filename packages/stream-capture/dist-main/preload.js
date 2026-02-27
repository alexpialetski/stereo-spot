"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { desktopCapturer } = require("electron");
electron_1.contextBridge.exposeInMainWorld("desktopCapturer", {
    getSources: async (opts) => {
        const srcs = await desktopCapturer.getSources(opts);
        return srcs.map((s) => ({
            id: s.id,
            name: s.name,
            thumbnail: s.thumbnail?.toDataURL() ?? "",
        }));
    },
});
electron_1.contextBridge.exposeInMainWorld("streamCapture", {
    createSession: (mode) => electron_1.ipcRenderer.invoke("create-session", mode),
    endSession: () => electron_1.ipcRenderer.invoke("end-session"),
    uploadChunk: (buffer) => electron_1.ipcRenderer.invoke("upload-chunk", buffer),
    getSession: () => electron_1.ipcRenderer.invoke("get-session"),
    requestStop: () => electron_1.ipcRenderer.invoke("request-stop"),
    onChunkUploaded: (cb) => {
        // Chunk index is returned from upload-chunk; UI will call getSession after each upload
        // So we don't need an event here; UI can pass a callback to the capture loop
        return () => { };
    },
    streamStarted: () => electron_1.ipcRenderer.send("stream-started"),
    streamStopped: () => electron_1.ipcRenderer.send("stream-stopped"),
});
