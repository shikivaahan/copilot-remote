import { apiFetch } from "./client";
import type { SessionHealth, SessionOut, SessionPreview } from "@/types";

export interface CreateSessionInput {
  name: string;
  repo: string;
  command: string;
}

export function listSessions(): Promise<SessionOut[]> {
  return apiFetch<SessionOut[]>("/api/sessions");
}

export function createSession(input: CreateSessionInput): Promise<SessionOut> {
  return apiFetch<SessionOut>("/api/sessions", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getSession(id: string): Promise<SessionOut> {
  return apiFetch<SessionOut>(`/api/sessions/${encodeURIComponent(id)}`);
}

export function deleteSession(id: string): Promise<void> {
  return apiFetch<void>(`/api/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function stopSession(id: string): Promise<void> {
  return apiFetch<void>(`/api/sessions/${encodeURIComponent(id)}/stop`, {
    method: "POST",
  });
}

export function restartSession(id: string): Promise<void> {
  return apiFetch<void>(`/api/sessions/${encodeURIComponent(id)}/restart`, {
    method: "POST",
  });
}

export function getSessionPreview(id: string): Promise<SessionPreview> {
  return apiFetch<SessionPreview>(
    `/api/sessions/${encodeURIComponent(id)}/preview`,
  );
}

export function getSessionHealth(id: string): Promise<SessionHealth> {
  return apiFetch<SessionHealth>(
    `/api/sessions/${encodeURIComponent(id)}/health`,
  );
}

export function listRepos(): Promise<string[]> {
  return apiFetch<string[]>("/api/repos");
}

export function listCommands(): Promise<string[]> {
  return apiFetch<string[]>("/api/commands");
}
