"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const path_1 = __importDefault(require("path"));
const sessions_js_1 = require("../api/sessions.js");
const encoder_js_1 = require("../capture/encoder.js");
const client_js_1 = require("../upload/client.js");
let mainWindow = null;
let session = null;
let chunkIndex = 0;
let uploadInProgress = false;
let stopRequested = false;
function getWindow() {
    return mainWindow;
}
function createWindow() {
    mainWindow = new electron_1.BrowserWindow({
        width: 520,
        height: 560,
        webPreferences: {
            preload: path_1.default.join(__dirname, "preload.js"),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    const isDev = process.env.NODE_ENV === "development" || !electron_1.app.isPackaged;
    mainWindow.loadFile(path_1.default.join(__dirname, "../dist/index.html"));
    mainWindow.on("closed", () => {
        mainWindow = null;
    });
}
electron_1.app.whenReady().then(() => {
    createWindow();
});
electron_1.app.on("window-all-closed", () => {
    electron_1.app.quit();
});
// --- IPC handlers ---
electron_1.ipcMain.handle("create-session", async (_, mode) => {
    if (session) {
        throw new Error("Session already active");
    }
    const res = await (0, sessions_js_1.createStreamSession)({ mode: mode ?? "sbs" });
    session = res;
    chunkIndex = 0;
    stopRequested = false;
    return {
        session_id: res.session_id,
        playlist_url: res.playlist_url,
        upload: res.upload,
    };
});
electron_1.ipcMain.handle("end-session", async () => {
    if (!session)
        return;
    const id = session.session_id;
    try {
        await (0, sessions_js_1.endStreamSession)(id);
    }
    finally {
        session = null;
    }
});
electron_1.ipcMain.handle("upload-chunk", async (_, buffer) => {
    if (!session) {
        throw new Error("No active session");
    }
    if (stopRequested)
        return;
    const credentials = session.upload;
    const raw = Buffer.from(buffer);
    const body = await (0, encoder_js_1.ensureMp4)(raw);
    await (0, client_js_1.uploadChunk)({
        sessionId: session.session_id,
        index: chunkIndex,
        body,
        credentials,
    });
    const index = chunkIndex;
    chunkIndex += 1;
    return { index };
});
electron_1.ipcMain.on("stream-started", () => {
    uploadInProgress = true;
});
electron_1.ipcMain.on("stream-stopped", () => {
    uploadInProgress = false;
});
electron_1.ipcMain.handle("get-session", () => {
    if (!session)
        return null;
    return {
        session_id: session.session_id,
        playlist_url: session.playlist_url,
        chunk_index: chunkIndex,
    };
});
electron_1.ipcMain.handle("request-stop", () => {
    stopRequested = true;
});
