import { app, BrowserWindow, ipcMain } from "electron";
import path from "path";
import { createStreamSession, endStreamSession } from "../api/sessions.js";
import type { CreateStreamSessionResponse } from "../api/types.js";
import { ensureMp4 } from "../capture/encoder.js";
import { uploadChunk } from "../upload/client.js";

let mainWindow: BrowserWindow | null = null;
let session: CreateStreamSessionResponse | null = null;
let chunkIndex = 0;
let uploadInProgress = false;
let stopRequested = false;

function getWindow(): BrowserWindow | null {
  return mainWindow;
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 520,
    height: 560,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  const isDev = process.env.NODE_ENV === "development" || !app.isPackaged;
  mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  createWindow();
});

app.on("window-all-closed", () => {
  app.quit();
});

// --- IPC handlers ---

ipcMain.handle("create-session", async (_, mode?: string) => {
  if (session) {
    throw new Error("Session already active");
  }
  const res = await createStreamSession({ mode: (mode as "sbs" | "anaglyph") ?? "sbs" });
  session = res;
  chunkIndex = 0;
  stopRequested = false;
  return {
    session_id: res.session_id,
    playlist_url: res.playlist_url,
    upload: res.upload,
  };
});

ipcMain.handle("end-session", async () => {
  if (!session) return;
  const id = session.session_id;
  try {
    await endStreamSession(id);
  } finally {
    session = null;
  }
});

ipcMain.handle("upload-chunk", async (_, buffer: ArrayBuffer) => {
  if (!session) {
    throw new Error("No active session");
  }
  if (stopRequested) return;
  const credentials = session.upload;
  const raw = Buffer.from(buffer);
  const body = await ensureMp4(raw);
  await uploadChunk({
    sessionId: session.session_id,
    index: chunkIndex,
    body,
    credentials,
  });
  const index = chunkIndex;
  chunkIndex += 1;
  return { index };
});

ipcMain.on("stream-started", () => {
  uploadInProgress = true;
});

ipcMain.on("stream-stopped", () => {
  uploadInProgress = false;
});

ipcMain.handle("get-session", () => {
  if (!session) return null;
  return {
    session_id: session.session_id,
    playlist_url: session.playlist_url,
    chunk_index: chunkIndex,
  };
});

ipcMain.handle("request-stop", () => {
  stopRequested = true;
});
