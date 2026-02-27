/** Temporary upload credentials returned by POST /stream_sessions */
export interface StreamUploadCredentials {
  access_key_id: string;
  secret_access_key: string;
  session_token: string;
  bucket: string;
  region: string;
  expires_at: string;
}

export interface CreateStreamSessionResponse {
  session_id: string;
  playlist_url: string;
  upload: StreamUploadCredentials;
}

export interface CreateStreamSessionRequest {
  mode?: "sbs" | "anaglyph";
}
