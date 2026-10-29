# API reference

Two interfaces: a small REST surface for state and a single WebSocket
endpoint that carries the terminal.

Interactive OpenAPI docs are served at `/docs` (ReDoc is disabled).

## Conventions

* All REST responses are JSON, except `204 No Content` responses, which
  have no body.
* Authentication is a signed `cr_session` cookie (`HttpOnly`, `Secure` in
  production, `SameSite=Strict`). The cookie is sent automatically by
  `fetch(..., {credentials: "include"})` in the frontend.
* State-changing requests (anything other than `GET`/`HEAD`/`OPTIONS`)
  must send `X-Requested-With: copilot-remote-app`, except login.
* Errors use FastAPI's `detail` field. `422` indicates request-schema
  validation errors; `400` indicates an allowlist failure; `401` means the session cookie is
  missing, invalid or expired; `403` means the CSRF header is missing or
  wrong; `404` means the session id is unknown; `409` is not currently used
  (a refused second attach is signalled over the WebSocket instead).

## REST endpoints

| Method | Path | Auth | CSRF | Notes |
|--------|------|------|------|-------|
| GET | `/health` | — | — | Liveness probe; no auth, no DB access |
| POST | `/api/auth/login` | — | exempt | Sets the `cr_session` cookie |
| POST | `/api/auth/logout` | — | ✓ | Clears the caller's cookie; no authentication dependency |
| GET | `/api/auth/me` | ✓ | — | Current user, or `401` |
| GET | `/api/sessions` | ✓ | — | List sessions |
| POST | `/api/sessions` | ✓ | ✓ | Create a session (201) |
| GET | `/api/sessions/{id}` | ✓ | — | One session |
| DELETE | `/api/sessions/{id}` | ✓ | ✓ | Kill the `tmux` session and remove the row |
| POST | `/api/sessions/{id}/stop` | ✓ | ✓ | Kill the `tmux` session, keep the row as `stopped` |
| POST | `/api/sessions/{id}/restart` | ✓ | ✓ | Kill the old session, return a replacement (new id) |
| GET | `/api/sessions/{id}/preview` | ✓ | — | Last 4 KB of recent PTY output |
| GET | `/api/sessions/{id}/health` | ✓ | — | Status, `tmux`/process liveness, active connections |
| GET | `/api/repos` | ✓ | — | Allowed repository paths |
| GET | `/api/commands` | ✓ | — | Allowed commands |
| WS | `/ws/sessions/{id}` | cookie | — | Terminal transport, see below |

### `POST /api/auth/login`

Request:

```json
{ "username": "alice", "password": "…" }
```

Response `200` (and the `Set-Cookie` header):

```json
{ "id": 1, "username": "alice", "created_at": "2026-01-01T00:00:00" }
```

Wrong username or password returns `401 Invalid credentials`.

### `POST /api/sessions`

Request:

```json
{
  "name": "review",
  "repo": "/home/user/projects/MyRepo",
  "command": "copilot"
}
```

`repo` and `command` are validated against the configured allowlists; a
value that is not on the list returns `400`. On success the response is
`201` with the created session:

```json
{
  "id": "0f2f6b1e-3b9a-4c6e-9a6a-6a6a6a6a6a6a",
  "name": "review",
  "repo": "/home/user/projects/MyRepo",
  "command": "copilot",
  "status": "running",
  "created_at": "2026-01-01T00:00:00",
  "last_activity_at": "2026-01-01T00:00:00"
}
```

The `id` is the server-generated UUID that is also the `tmux` session name.

### `GET /api/sessions/{id}/health`

```json
{
  "id": "0f2f…",
  "status": "running",
  "tmux_session_exists": true,
  "process_alive": true,
  "active_connections": 1,
  "last_activity_at": "2026-01-01T00:05:00",
  "output_buffer_bytes": 131072
}
```

### `GET /api/sessions/{id}/preview`

```json
{ "id": "0f2f…", "text": "…", "bytes": 4096 }
```

Slices at most 4096 raw bytes from the session's output ring buffer, then
decodes as UTF-8 with replacement. The reported `bytes` counts the encoded
response text, so it can exceed 4096 for invalid or split UTF-8 sequences.
When that text is blank and a running session still exists, the server
falls back to `tmux capture-pane`, likewise slicing before decoding.

## WebSocket protocol

Endpoint: `GET /ws/sessions/{session_id}` (WebSocket upgrade).

The cookie is checked before the upgrade. On an invalid cookie, an unknown
session, or a refused second attach, the server accepts the socket and
closes it with code **1008** (policy violation); for the multi-attach
refusal it first sends an `error` frame.

### Wire format

* **Binary frames** carry terminal I/O.
  * Client → server: raw bytes typed by the user (xterm.js `onData`).
  * Server → client: PTY stdout bytes.
  * There is no protocol layer — bytes are forwarded verbatim.
* **Text frames** are UTF-8 JSON and carry control messages only.

### Client → server

| Message | Effect |
|---------|--------|
| `{"type": "resize", "rows": int, "cols": int}` | Resize the PTY (`SIGWINCH`). Subsequent resize controls enforce `0 < rows, cols < 1000`; the initial size negotiation does not apply this bound. |
| `{"type": "signal", "name": "SIGINT" \| "SIGTERM" \| "SIGHUP"}` | Send the signal to the process group of the attached PTY. |
| `{"type": "ping"}` | Liveness probe. |

Unknown message types are ignored. Malformed JSON is ignored.

### Server → client

| Message | Meaning |
|---------|---------|
| `{"type": "pong"}` | Reply to `ping`. |
| `{"type": "status", "state": "running" \| "exited" \| "errored" \| "stopped", "rows": int, "cols": int}` | Sent right after the connection is established; `rows`/`cols` echo the negotiated size. |
| `{"type": "error", "message": "..."}` | Error such as "session already attached"; attach failures are followed by a `1008` close. |

### Connection sequence

1. The client opens the socket and immediately sends a `resize` frame with
   the current terminal geometry (the server defaults to 24x80 until it
   receives one).
2. The server attaches a fresh PTY to the `tmux` session and sends a
   `status` frame.
3. Binary frames flow in both directions.
4. The client sends `ping` every 25 seconds; the server replies `pong`.
5. When the socket closes, the server closes the PTY and decrements the
   active connection count. The `tmux` session keeps running.

### Reconnection

The frontend reconnects with exponential backoff: a 1s initial base delay
doubling to a 30s base cap, with ±20% jitter applied afterward (up to 36s).
This avoids several tabs reconnecting in lockstep. A fresh `resize` is sent
after every reconnect. Because persistent state lives in `tmux` rather than
the socket, reconnecting reattaches to the live session.

## Status values

| Status | Meaning |
|--------|---------|
| `running` | the `tmux` session exists and the command process is alive |
| `exited` | the row persists but the command or `tmux` session has ended |
| `stopped` | the user stopped the session; the row is kept for status/history |
| `errored` | declared status value; current create/attach failures return errors rather than assigning it |
