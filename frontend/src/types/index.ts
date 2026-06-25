export type SessionStatus = "running" | "exited" | "errored";

export interface UserOut {
  id: number;
  username: string;
  created_at: string;
}

export interface SessionOut {
  id: string;
  name: string;
  repo: string;
  command: string;
  status: SessionStatus;
  created_at: string;
  last_activity_at: string;
}

export interface SessionHealth {
  id: string;
  status: SessionStatus;
  tmux_session_exists: boolean;
  process_alive: boolean;
  active_connections: number;
  last_activity_at: string;
  output_buffer_bytes: number;
}

export interface SessionPreview {
  id: string;
  text: string;
  bytes: number;
}
