# Deployment

## Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.12+ | backend |
| Node.js | 20+ | frontend build |
| tmux | any recent | the persistence layer; must be on `PATH` for the service account |
| Tailscale | optional | only for remote access |

The backend needs a `tmux` server it can talk to: it creates detached
sessions with `tmux new-session -d` and attaches to them with
`tmux attach-session`. If `tmux` is missing, session creation fails with
`tmux is not installed`.

Install and authenticate GitHub Copilot CLI separately as the backend's
service account if you want `copilot` sessions. A `bash` session needs no
provider access; the app's local account does not authenticate to GitHub.

## Install

### 1. System packages (Debian/Ubuntu)

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

`pip install -e ".[dev]"` also installs the `copilot-remote` console script
used for user management.

### 3. Configuration

```bash
cp ../config.example.yaml ./config.yaml
mkdir -p ../data
```

Edit `./config.yaml`:

```yaml
bind: "127.0.0.1"
port: 8000
database_url: "sqlite:///./copilot_remote.db"
session_secret: "<openssl rand -hex 32>"
secure_cookies: true
repos:
  - /home/user/projects/MyRepo
commands:
  - copilot
  - bash
```

Generate a session secret:

```bash
openssl rand -hex 32
```

The app refuses to start if `session_secret` is shorter than 16 characters
or is still the placeholder value from `config.example.yaml`.

The configuration file is looked up at `./config.yaml` relative to the
working directory, or at the path in `COPILOT_REMOTE_CONFIG`.

### 4. First user

```bash
copilot-remote create-user
# prompts for username and password
```

Other CLI commands:

```bash
copilot-remote init-config --config ./config.yaml   # copy the example config
copilot-remote reset-password --username alice       # rotate a password
```

### 5. Frontend

The commands below start from the repository root in separate shells;
if continuing from the backend setup, return there first with `cd ..`.
Distribution `nodejs` packages may be older than Node 20; check
`node --version` and use an appropriate Node installation before proceeding.

Development mode — Vite dev server on `http://localhost:5173`, proxying
`/api` and `/ws` to `127.0.0.1:8000`:

```bash
cd frontend
npm install
npm run dev
```

Run the backend with HTTP-only cookies so the browser accepts them over
plain HTTP:

```bash
cd backend
source .venv/bin/activate
COPILOT_REMOTE_SECURE_COOKIES=false uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Production build — Vite writes to `backend/frontend_dist/`, which FastAPI
serves as a single-page app:

```bash
cd frontend
npm ci
npm run build          # tsc --noEmit && vite build -> ../backend/frontend_dist
cd ../backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

`--workers 1` matters: the session registry is in-process state (see
[architecture.md](architecture.md#concurrency-model)).

## Configuration reference

The full schema lives in [`config.example.yaml`](../config.example.yaml).

| Path | Default | Notes |
|------|---------|-------|
| `bind` | `127.0.0.1` | Address reported at startup. The listening socket is set by uvicorn's `--host`/`--port`. |
| `port` | `8000` | Port reported at startup; uvicorn decides the real one. |
| `database_url` | `sqlite:///./copilot_remote.db` | SQLAlchemy URL. |
| `session_secret` | — (required) | Cookie signing key. **Generate with `openssl rand -hex 32`.** Rotating it invalidates all cookies. |
| `secure_cookies` | `true` | Keep `true` for HTTPS/Tailscale Serve. Set `COPILOT_REMOTE_SECURE_COOKIES=false` only for local HTTP dev. |
| `environment` | `development` | Reported at startup. |
| `repos` | `[]` | Absolute paths of allowed repository roots. |
| `commands` | `[]` | Allowed commands. Bare names (`bash`) or absolute paths (`/usr/bin/copilot`). |
| `session.output_buffer_bytes` | `131072` | 128 KB in-memory ring buffer per session, used by the dashboard preview. |
| `session.status_poll_interval_seconds` | `5` | How often the background poller refreshes session status. |
| `session.idle_timeout_seconds` | `0` | Declared but **not enforced**; no idle expiry is implemented. Commands can still exit on their own. |
| `session.multi_attach` | `shared` | `shared` = several browser tabs may attach; `reject` = a second attach is refused. |

### Environment variables

Settings accept the `COPILOT_REMOTE_` prefix; nested keys
use a double underscore:

```bash
COPILOT_REMOTE_PORT=9000
COPILOT_REMOTE_SESSION__OUTPUT_BUFFER_BYTES=131072
COPILOT_REMOTE_SECURE_COOKIES=false
COPILOT_REMOTE_CONFIG=/etc/copilot-remote/config.yaml
```

Precedence: environment variables > YAML file > field defaults.

List-valued environment settings use JSON, for example
`COPILOT_REMOTE_COMMANDS='["bash"]'`. A nested environment override replaces
the corresponding top-level YAML section rather than deeply merging it;
repeat any other non-default `session` settings you need in environment
variables too.

## Remote access with Tailscale

Expose the app through Tailscale Serve, not through a public interface:

```bash
# On the host:
sudo tailscale up
tailscale serve --bg 8000
tailscale serve status
```

On the phone, install the Tailscale app, log in to the same tailnet, then
open the HTTPS URL printed by `tailscale serve status` in Safari (iOS) or
Chrome (Android). "Add to Home Screen" installs the PWA.

Why Serve rather than browsing `http://100.x.y.z:8000/` directly?

* The backend stays bound to `127.0.0.1`; Serve proxies it privately to
  authenticated tailnet devices.
* PWA service workers and `Secure` cookies require a secure context, and
  Serve gives the phone an HTTPS URL without exposing the app publicly.

## systemd

The repository ships `copilot-remote.service`. It expects the checkout at
`/opt/copilot-remote` with a virtualenv in `backend/.venv` and the
configuration at `/etc/copilot-remote/config.yaml`.

Before enabling the unit, install/build the app at that location (or edit
`WorkingDirectory` and `ExecStart` to match your checkout). Create
`/etc/copilot-remote/config.yaml` from your edited configuration, make it
readable only by the service account/administrator, and use an absolute
SQLite URL pointing to a directory writable by that account. Create the
login user using the same `COPILOT_REMOTE_CONFIG` and database. Ensure the
account can access the allowed repositories and locate `tmux` and `copilot`;
systemd does not load your interactive shell's PATH. Copilot CLI must already
be installed and authenticated for that account; the web login does not
authenticate to GitHub.

```bash
sudo cp copilot-remote.service /etc/systemd/system/
sudo sed -i 's/USER_PLACEHOLDER/youruser/g' /etc/systemd/system/copilot-remote.service
sudo systemctl daemon-reload
sudo systemctl enable --now copilot-remote
journalctl -u copilot-remote -f
```

The unit sets `NoNewPrivileges`, `PrivateTmp`, `ProtectKernelTunables`,
`ProtectKernelModules` and `ProtectControlGroups`. It deliberately does not
enable `ProtectHome`/`ProtectSystem=strict`, because the service
intentionally launches shells inside allowlisted repositories.

## Launch commands

Production-style local service behind Tailscale Serve:

```bash
cd /path/to/copilot-remote/backend
source .venv/bin/activate
export COPILOT_REMOTE_CONFIG=/path/to/copilot-remote/backend/config.yaml
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

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

1. Open the Tailscale Serve HTTPS URL (or `http://localhost:5173` in dev).
2. Log in with a local account created by `copilot-remote create-user`.
3. Tap `Create session`, pick an allowlisted repository and an allowlisted
   command (`copilot`, `bash`, …).
4. Open the session card to use the terminal. The helper bar sends Esc, Tab,
   arrows, `/`, Enter and Ctrl-C/Ctrl-D.
5. If the phone sleeps or the network changes, reopen the same session: the
   `tmux`-backed process keeps running and the terminal reattaches.
6. Use `Stop` to terminate the `tmux` session (the row is kept as
   `stopped`), `Restart` to create a replacement session, or `Delete` to
   kill the `tmux` session and remove the saved row.

## Verification

Backend test suite (requires `tmux` on `PATH`):

```bash
cd backend && source .venv/bin/activate
pytest -q --cov=app --cov-fail-under=80
```

Frontend:

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

Manual release smoke test, from the phone over the Tailscale Serve HTTPS URL:

1. Log in.
2. Create a `bash` session.
3. Type commands; use Tab/arrows/Ctrl-C/Ctrl-D; rotate the phone to resize.
4. Disconnect and reconnect the browser and confirm the same `tmux` session
   returns.
5. Restart the backend service and reconnect to the existing session.
6. If GitHub Copilot CLI is installed and authenticated locally, create a
   `copilot` session and verify `/help` renders in the remote terminal.

Steps 1–5 need only `bash`; step 6 needs a locally authenticated Copilot
CLI.
