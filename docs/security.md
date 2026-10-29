# Security design

Copilot Remote gives an authenticated user a shell on the machine that runs
it. The security posture is therefore that of a remote-administration tool:
the goal is to keep it off the public internet and to make the few
remaining exposures explicit, not to make it safe for untrusted users.

**This project has not been security-audited.** Nothing below should be read
as a claim of production-grade hardening.

## Threat model

Assumed:

* The operator is the owner of the host and is trusted.
* The device sits on a private network (a Tailscale tailnet) whose members
  are trusted.
* The host itself is not compromised, and the `tmux`/Copilot CLI binaries
  are the ones the operator installed.

Not assumed, and therefore not defended against:

* Untrusted users on the same tailnet. Every authenticated account sees every
  session; see [Limitations](#limitations).
* A hostile local user on the host. Sessions run with the privileges of the
  service account.
* Physical access to the host or to an unlocked browser session.
* Traffic interception outside the tailnet. Confidentiality of the session
  depends on the transport in front of the app (HTTPS via Tailscale Serve).

Out of scope by design: multi-tenancy, public exposure, and untrusted
terminal input parsing.

## Deployment boundary

* The backend binds to `127.0.0.1` by default. `bind` in the configuration
  is the address the app *reports* at startup; the listening socket is
  controlled by the uvicorn invocation (`--host` / `--port`).
* Exposure is intended to go through **Tailscale Serve**, which terminates
  HTTPS for authenticated tailnet devices and proxies to the loopback
  listener. The backend never sees a public interface.
* Do not put the app behind a public reverse proxy. The CORS policy is
  deliberately empty (`allow_origins=[]`): the SPA is single-origin, and
  cross-origin requests are not expected or supported.

Why HTTPS matters beyond encryption: the PWA service worker and the
`Secure` session cookie both require a secure context, so plain HTTP is a
development-only mode.

## Authentication

* Passwords are hashed with **bcrypt at cost factor 12** (passlib).
  Malformed stored hashes are treated as a non-match rather than raising.
* The login endpoint returns a generic `401 Invalid credentials` for both
  unknown users and wrong passwords.
* Local accounts are created out of band with the `copilot-remote create-user`
  CLI command; there is no registration, invitation, or password-reset
  flow over HTTP. `copilot-remote reset-password` rotates a password from
  the host's shell.
* The `session_secret` must be at least 16 characters and must not be the
  placeholder shipped in `config.example.yaml`; the app refuses to start
  otherwise. Generate one with `openssl rand -hex 32`.
* There is **no rate limiting or lockout** on the login endpoint. On a
  trusted network this is an accepted trade-off; on any wider network it
  would need to be added.

## Session cookie

| Property | Value | Reason |
|----------|-------|--------|
| Name | `cr_session` | |
| Value | `itsdangerous.TimestampSigner` signature of the user id | stateless, no session table |
| `HttpOnly` | yes | not readable from JavaScript |
| `Secure` | `true` unless `COPILOT_REMOTE_SECURE_COOKIES=false` | HTTPS-only in production |
| `SameSite` | `Strict` | not sent on cross-site requests |
| `Path` | `/` | |
| `Max-Age` | 30 days | expired cookies are rejected server-side |

Consequences:

* The cookie is a bearer credential. Anyone who obtains it has the account's
  access until it expires or the secret is rotated.
* The signer salt (`copilot-remote-session`) is versioned in code: changing
  it invalidates every outstanding cookie at once. Rotating
  `session_secret` has the same effect for cookies signed with the old key.
* Logout clears the browser cookie but does not revoke copied credentials.
  Password reset also does not invalidate existing cookies. WebSockets are
  authenticated at connection time, not continuously; secret rotation does
  not itself close an already-open terminal connection.
* Setting `secure_cookies: false` (or `COPILOT_REMOTE_SECURE_COOKIES=false`)
  downgrades the cookie to a non-`Secure` cookie. Use it only for local
  HTTP development.

## CSRF protection

`POST`, `DELETE` and other state-changing methods require the header

```
X-Requested-With: copilot-remote-app
```

`GET`, `HEAD` and `OPTIONS` are exempt, and login does not require the
header. Cross-origin custom headers require a CORS preflight; the empty
CORS policy does not grant permission. This is defence in depth on top
of `SameSite=Strict`, not proof that a caller is the SPA: non-browser
clients can send the header too.

The WebSocket handshake is not covered by this header check — it relies on
the cookie plus `SameSite=Strict`.

## WebSocket endpoint

`/ws/sessions/{id}`:

* The `cr_session` cookie is validated **before** the connection is
  upgraded. The handler accepts the socket and then closes it with code
  `1008` (policy violation) so the browser receives an explicit close frame
  rather than an opaque handshake failure.
* An unknown session id is likewise closed with `1008`.
* With `session.multi_attach: reject`, a second attachment is refused with
  an `error` frame followed by a `1008` close.
* Signals are limited to `SIGINT`, `SIGTERM` and `SIGHUP`, and are sent to
  the *process group* of the attached PTY.

The backend does not check the `Origin` header of the WebSocket handshake;
it relies on the browser's `SameSite=Strict` cookie rules to prevent a
cross-site page from opening an authenticated socket.

## Terminal execution boundary

* **Allowlists.** `repos` and `commands` in the configuration decide what a
  session may run. Repository paths are canonicalised with
  `os.path.realpath` on both sides and compared exactly; commands are
  compared byte-for-byte (with an extra `realpath` comparison for absolute
  paths). Anything not on the list is rejected with a `400`.
* **No shell interpolation.** All subprocess calls pass argv lists. There is
  no `shell=True` anywhere in `backend/app/`; `backend/tests/test_shell_safety.py`
  parses the AST of every module in `app/` and fails the build if one
  appears.
* **Session identity.** The `tmux` session name is a server-generated UUID.
  It is regex-validated (`UUID_RE`) before every `tmux` call, and it is the
  only identifier ever handed to `tmux`. The user-supplied session *name*
  is a display label and never reaches a shell.
* **Command hygiene.** The command is additionally rejected if it has
  surrounding whitespace, a NUL byte or a newline.
* **Host privileges.** The terminal runs with the privileges of the backend
  account; allowlists constrain session creation, not later shell actions.
  The shipped systemd unit runs the service
  as the account you put in `User=` (use a dedicated non-root account; the
  unit ships a `USER_PLACEHOLDER` you must replace) with `NoNewPrivileges`,
  `PrivateTmp`, `ProtectKernelTunables`, `ProtectKernelModules` and
  `ProtectControlGroups`,
  and deliberately does **not** enable `ProtectHome`/`ProtectSystem=strict`,
  because the service intentionally launches shells inside allowlisted
  repositories.
* **tmux reach.** The service account needs permission to talk to the `tmux`
  server; sessions it creates are visible to that account's `tmux` socket.

## Data at rest

* SQLite holds user names, bcrypt hashes and session metadata (repo path,
  command, status, timestamps). Passwords are never stored in clear text.
* The output ring buffer (default 128 KB per session) lives in memory only
  and is lost on backend restart.
* The database file is created by the service account; protect it with
  normal filesystem permissions.

## Limitations

These are real gaps, not oversights hidden behind wording:

* **No audit has been performed.** No penetration test, no third-party
  review, no formal threat model document.
* **No per-user session isolation.** Any authenticated account can list,
  stop, restart, delete and attach to *any* session. The model assumes a
  single trusted operator; multiple accounts are not a supported multi-user
  setup.
* **No login rate limiting or lockout.** Brute-force protection is left to
  the network boundary (tailnet membership) and the operator's judgement.
* **No origin check on the WebSocket handshake**, and no separate
  authorisation token for the socket; protection rests on `SameSite=Strict`
  and the cookie.
* **Terminal output is trusted content.** Copilot (or a command it runs)
  can print arbitrary escape sequences; `xterm.js` renders them. There is
  no filtering of terminal control sequences.
* **The allowlist is the only command-level restriction.** An allowlisted
  `bash` gives full shell access to the service account within the
  allowlisted working directory (and, since `cd` works, effectively beyond
  it — the allowlist restricts where a session *starts*, not what it can do).
* **`secure_cookies: false`** removes the `Secure` flag; this is intended
  for local HTTP development only.
* **No secret rotation tooling.** Rotating `session_secret` is a manual
  edit plus a restart.
* **Single worker.** The session registry is in-process state, so the
  service is designed to run with `--workers 1`. Multiple workers would
  each keep their own registry and hydrate independently.

## Checklist for a real deployment

1. Generate a fresh `session_secret` (`openssl rand -hex 32`).
2. Keep `bind`/`--host` on `127.0.0.1`; expose only via Tailscale Serve.
3. Leave `secure_cookies: true`.
4. Use a dedicated service account with the minimum repository allowlist.
5. Create exactly the accounts you intend to use (`copilot-remote create-user`).
6. Keep the host patched; the app runs a real shell for whoever logs in.
