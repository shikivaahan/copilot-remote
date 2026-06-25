# Copilot Remote

> Self-hosted web app that lets you drive **GitHub Copilot CLI** from your
> phone over Tailscale. The app is a **transparent terminal transport**:
> it moves bytes between a real PTY and a WebSocket, and never inspects
> Copilot output. If Copilot adds a new slash command tomorrow, it works
> remotely with zero app changes.

## Architecture (one-liner)

```
phone (xterm.js) <-> WebSocket <-> FastAPI <-> ptyprocess(tmux attach-session) <-> tmux server <-> copilot
```

* `tmux` is the **persistent** layer (owns the child process).
* The PTY spawned per WebSocket connection is a **transient** view of tmux.
* Backend never parses terminal bytes; the app can be reimplemented in
  any language without losing Copilot functionality.

## Repository layout

```
backend/   # Python 3.12+, FastAPI, SQLModel, ptyprocess, tmux
frontend/  # React 18 + TS + Vite + Tailwind + xterm.js + vite-plugin-pwa
config.example.yaml      # example configuration
copilot-remote.service   # systemd unit
.github/workflows/ci.yml # CI (backend pytest + frontend typecheck/test/build)
```

## Quickstart

### 1. Install dependencies

System packages (Debian/Ubuntu):
```bash
sudo apt-get install -y tmux python3.12 python3.12-venv nodejs npm
```

### 2. Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Configuration

```bash
cp ../config.example.yaml ./config.yaml
# Edit ./config.yaml:
#   - bind: 127.0.0.1
#   - port: 8000
#   - session_secret: <openssl rand -hex 32>
#   - secure_cookies: true
#   - repos: [/path/to/your/project, ...]
#   - commands: [copilot, bash]
mkdir -p ../data
```

Generate a session secret:
```bash
openssl rand -hex 32
```

### 4. Create the first user

```bash
copilot-remote create-user
# Enter username and password at the prompts.
```

### 5. Frontend (dev mode)

In another shell, run the backend with HTTP-only dev cookies:
```bash
cd backend
source .venv/bin/activate
COPILOT_REMOTE_SECURE_COOKIES=false uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then start Vite:
```bash
cd ../frontend
npm install
npm run dev
# Vite dev server on http://localhost:5173, proxies /api and /ws to :8000.
```

### 6. Frontend (production build)

```bash
npm run build
# Output goes to backend/frontend_dist/ and is served by FastAPI.
```

## Production deployment

```bash
# Build the frontend first; FastAPI will serve it.
cd backend && source .venv/bin/activate
cd ../frontend && npm ci && npm run build
cd ../backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Expose via Tailscale Serve only:
```bash
# On the laptop:
sudo tailscale up
tailscale serve --bg 8000
tailscale serve status
```

On the phone, install the Tailscale app, log in, then open
the HTTPS URL shown by `tailscale serve status` in Safari (iOS) or Chrome
(Android). Use "Add to Home Screen" to install the PWA.

Why Serve instead of direct `http://100.x.y.z:8000/`?

* The backend should stay bound to `127.0.0.1`; Serve proxies it privately to
  authenticated tailnet devices.
* PWA service workers and production `Secure` cookies require a secure context.
  Tailscale Serve gives the phone an HTTPS URL without exposing the app to the
  public internet.

### systemd

Copy the unit file and fill in your user:
```bash
sudo cp copilot-remote.service /etc/systemd/system/
sudo sed -i 's/USER_PLACEHOLDER/youruser/g' /etc/systemd/system/copilot-remote.service
sudo systemctl daemon-reload
sudo systemctl enable --now copilot-remote
journalctl -u copilot-remote -f   # follow logs
```

## Security model

* Bind to `127.0.0.1`; expose only via Tailscale Serve.
* `session_secret` must be at least 16 characters (>= 64 recommended);
  generate with `openssl rand -hex 32`.
* Bcrypt password hash (cost 12).
* Session cookie: `HttpOnly`, `Secure` (in production), `SameSite=Strict`.
* CSRF: state-changing REST endpoints require the `X-Requested-With:
  copilot-remote-app` header (browsers cannot set custom headers on
  cross-origin simple requests, so this defeats naïve CSRF).
* Repo and command allowlists are validated server-side. Repo paths are
  exact-matched after `realpath`. Commands are exact-matched. The
  tmux session name is **always** a server-generated UUID, never
  user input.
* All subprocess calls use argv lists (no `shell=True` anywhere —
  enforced by an AST scan in CI).

## Configuration reference

See `config.example.yaml` for the full schema. Key options:

| Path | Default | Notes |
|------|---------|-------|
| `bind` | `127.0.0.1` | Listen address. **Do not** bind to 0.0.0.0; use Tailscale Serve. |
| `port` | `8000` | Listen port. |
| `database_url` | `sqlite:///./copilot_remote.db` | SQLAlchemy URL. |
| `session_secret` | — (required) | itsdangerous salt. **Generate with `openssl rand -hex 32`**. |
| `secure_cookies` | `true` | Keep `true` for HTTPS/Tailscale Serve. Set `COPILOT_REMOTE_SECURE_COOKIES=false` only for local HTTP dev. |
| `repos` | `[]` | Absolute paths to allowed repo roots. |
| `commands` | `[]` | Allowed commands. Bare names like `bash` or absolute paths like `/usr/bin/copilot`. |
| `session.output_buffer_bytes` | `131072` | 128KB ring buffer per session for the dashboard preview. |
| `session.status_poll_interval_seconds` | `5` | How often the background poller updates DB. |
| `session.multi_attach` | `shared` | `shared` = multiple browser tabs can attach. `reject` = 409 on second attach. |

Equivalent environment variables: prefix with `COPILOT_REMOTE_`, e.g.
`COPILOT_REMOTE_PORT=9000` overrides `port`. Nested keys use double
underscore: `COPILOT_REMOTE_SESSION__OUTPUT_BUFFER_BYTES=131072`.

## Launch commands

Production-style local service behind Tailscale Serve:
```bash
cd /path/to/copilot-remote/backend
source .venv/bin/activate
export COPILOT_REMOTE_CONFIG=/path/to/copilot-remote/backend/config.yaml
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

In another shell:
```bash
tailscale serve --bg 8000
tailscale serve status
```

HTTP-only local development:
```bash
cd /path/to/copilot-remote/backend
source .venv/bin/activate
export COPILOT_REMOTE_CONFIG=/path/to/copilot-remote/backend/config.yaml
export COPILOT_REMOTE_SECURE_COOKIES=false
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

cd /path/to/copilot-remote/frontend
npm run dev
```

## User flow

1. Open the Tailscale Serve HTTPS URL on your phone.
2. Log in with the local user created by `copilot-remote create-user`.
3. Tap `Create session`, pick an allowlisted repository, and choose `copilot`
   or another allowlisted command.
4. Open the session card to use the terminal. The helper bar sends Esc, Tab,
   arrows, slash, Enter, and Ctrl-C/Ctrl-D.
5. If the phone sleeps or the network changes, reopen the same session; the
   tmux-backed process keeps running.
6. Use `Stop` to terminate the tmux session, `Restart` to create a replacement,
   or `Delete` to remove the saved session row.

## REST API

| Method | Path | Auth | CSRF | Notes |
|--------|------|------|------|-------|
| GET | `/health` | — | — | Liveness probe |
| POST | `/api/auth/login` | — | exempt | Sets `cr_session` cookie |
| POST | `/api/auth/logout` | ✓ | ✓ | Clears `cr_session` |
| GET | `/api/auth/me` | ✓ | — | Current user |
| GET | `/api/sessions` | ✓ | — | List sessions |
| POST | `/api/sessions` | ✓ | ✓ | Create session |
| GET | `/api/sessions/{id}` | ✓ | — | Get one session |
| DELETE | `/api/sessions/{id}` | ✓ | ✓ | Kill tmux if present, remove row |
| POST | `/api/sessions/{id}/stop` | ✓ | ✓ | Kill tmux, keep row as `stopped` |
| POST | `/api/sessions/{id}/restart` | ✓ | ✓ | Kill old session, return replacement |
| GET | `/api/sessions/{id}/preview` | ✓ | — | Last 4KB of PTY output |
| GET | `/api/sessions/{id}/health` | ✓ | — | Status + active connections |
| GET | `/api/repos` | ✓ | — | Allowed repos |
| GET | `/api/commands` | ✓ | — | Allowed commands |
| WS | `/ws/sessions/{id}` | cookie | — | See protocol below |

## WebSocket protocol

### Wire format

* **Binary frames** carry terminal I/O. Client-to-server: typed by user
  (xterm.js `onData`). Server-to-client: PTY stdout. **No protocol
  layer; bytes are forwarded verbatim.**
* **Text frames (JSON, UTF-8)** carry control messages:
  * Client → Server: `{"type": "resize", "rows": int, "cols": int}`,
    `{"type": "signal", "name": "SIGINT"|"SIGTERM"|"SIGHUP"}`,
    `{"type": "ping"}`.
  * Server → Client: `{"type": "pong"}`,
    `{"type": "status", "state": "running"|"exited"|"errored"|"stopped"}`,
    `{"type": "error", "message": "..."}`.

## Session lifecycle

Sessions are stored in SQLite and backed by tmux. On backend startup, the
manager hydrates rows from the database and reconciles them with live tmux
sessions, so a browser can reconnect after the backend restarts. Output preview
buffers are in memory, so previews start fresh after a backend restart.

Status values:

| Status | Meaning |
|--------|---------|
| `running` | tmux session exists and the command process is alive |
| `exited` | persisted session remains, but the command/tmux session has ended |
| `stopped` | user stopped the session; row remains for status/history |
| `errored` | backend could not create or attach the session cleanly |

`session.multi_attach: shared` allows multiple browser tabs to attach to the
same tmux session. `reject` returns a policy error when another tab is already
attached.

## Non-goals

* Not a Copilot wrapper. Not a GitHub API client. Not a multi-tenant
  SaaS. Not exposed to the public internet. The architecture transports
  raw terminal I/O and understands nothing about Copilot's output.

## Testing

Backend:
```bash
cd backend && source .venv/bin/activate
pytest -q --cov=app --cov-fail-under=80
```

Frontend:
```bash
cd frontend
npm run typecheck
npm test -- --run
npm run build
```

Manual release smoke:
```bash
# From the phone over the Tailscale Serve HTTPS URL:
# 1. Log in.
# 2. Create a bash session.
# 3. Type commands, use Tab/arrows/Ctrl-C/Ctrl-D, and resize the phone.
# 4. Disconnect/reconnect the browser and confirm the same tmux session returns.
# 5. Restart the backend service and reconnect to the existing session.
# 6. If GitHub Copilot CLI is locally installed and authenticated, create a
#    copilot session and verify `/help` renders in the remote terminal.
```

## License

Personal use, all rights reserved by the owner.
