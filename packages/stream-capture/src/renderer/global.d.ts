export {};

declare global {
  interface Window {
    desktopCapturer?: {
      getSources: (opts: { types: string[] }) => Promise<
        { id: string; name: string; thumbnail: string }[]
      >;
    };
    streamCapture?: {
      createSession: (mode?: string) => Promise<{
        session_id: string;
        playlist_url: string;
        upload: unknown;
      }>;
      endSession: () => Promise<void>;
      uploadChunk: (buffer: ArrayBuffer) => Promise<{ index: number }>;
      getSession: () => Promise<{
        session_id: string;
        playlist_url: string;
        chunk_index: number;
      } | null>;
      requestStop: () => Promise<void>;
      streamStarted: () => void;
      streamStopped: () => void;
    };
  }
}
