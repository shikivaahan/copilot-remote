export const API_BASE = "";

export const CSRF_HEADER = "X-Requested-With";
export const CSRF_HEADER_VALUE = "copilot-remote-app";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function defaultHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    [CSRF_HEADER]: CSRF_HEADER_VALUE,
  };
}

export interface ApiFetchOptions extends Omit<RequestInit, "headers"> {
  headers?: Record<string, string>;
}

export async function apiFetch<T>(
  path: string,
  init: ApiFetchOptions = {},
): Promise<T> {
  const { headers: extraHeaders, ...rest } = init;
  const headers: Record<string, string> = {
    ...defaultHeaders(),
    ...(extraHeaders ?? {}),
  };

  // The CSRF header is part of the default headers and is sent on every
  // request, including mutating ones (POST/PUT/PATCH/DELETE). The backend
  // enforces this header on all state-changing endpoints (see plan §6.5).
  void rest.method;

  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    credentials: "include",
    headers,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  let payload: unknown = null;
  if (contentType.includes("application/json")) {
    payload = await response.json().catch(() => null);
  } else {
    payload = await response.text().catch(() => null);
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    if (
      payload &&
      typeof payload === "object" &&
      "detail" in payload &&
      typeof (payload as { detail: unknown }).detail === "string"
    ) {
      message = (payload as { detail: string }).detail;
    } else if (typeof payload === "string" && payload.length > 0) {
      message = payload;
    }
    throw new ApiError(response.status, message);
  }

  return payload as T;
}
