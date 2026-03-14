# 🖥 Browser-Based Linux Terminal

A **production-quality**, browser-based interactive Linux terminal built as a portfolio project targeting infrastructure companies like **Neverinstall**, CodeSandbox, and Gitpod.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Browser (xterm.js)                  │
│  ┌──────────────────────────────────────────────┐    │
│  │  FitAddon   WebLinksAddon   256-color theme  │    │
│  └──────────────────────────────────────────────┘    │
└────────────────────┬────────────────────────────────┘
                     │ WebSocket (ws:// or wss://)
                     │ • Raw keystrokes / binary data  ↑↓
                     │ • JSON resize events            →
                     │ • Token auth (?token=...)       →
┌────────────────────┴────────────────────────────────┐
│              FastAPI WebSocket endpoint              │
│              /ws?token=<SECRET_TOKEN>                │
│  ┌───────────────┐        ┌───────────────────────┐ │
│  │  ws_to_pty()  │        │     pty_to_ws()        │ │
│  │  asyncio task │        │     asyncio task       │ │
│  └──────┬────────┘        └──────────┬─────────────┘ │
└─────────┼───────────────────────────┼───────────────┘
          │ stdin write               │ stdout read
┌─────────┴───────────────────────────┴───────────────┐
│           PTY Process  (ptyprocess library)          │
│                  bash --login                        │
│          One PTY per WebSocket connection            │
└──────────────────────────────────────────────────────┘
```

---

## Features

| Feature | Details |
|---|---|
| **Full PTY** | Real bash shell — arrow keys, Ctrl+C, tab completion all work |
| **256 colours** | `TERM=xterm-256color` + truecolor support |
| **Window resize** | Browser resize events propagate via `setwinsize()` |
| **Token auth** | `?token=` query parameter validated on every connection |
| **Idle timeout** | Session auto-kills after configurable inactivity period (default 10 min) |
| **Multiple sessions** | Each WebSocket spawns an independent PTY |
| **Crash-safe server** | All exceptions are caught; server never goes down on client disconnect |
| **Docker-ready** | Single `docker run` to deploy anywhere |

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Backend** | FastAPI + Uvicorn | Async-first, native WebSocket support, fast |
| **PTY bridge** | `ptyprocess` | Spawns real PTYs; handles signals, resize, EOF |
| **WebSocket** | Starlette (built into FastAPI) | Zero extra deps |
| **Frontend** | xterm.js 5 (CDN) | Industry-standard terminal emulator for the web |
| **Terminal addons** | xterm-addon-fit, xterm-addon-web-links | Responsive sizing, clickable URLs |
| **Containerisation** | Docker (python:3.11-slim) | Reproducible, portable deployment |

---

## Running Locally

### Prerequisites

- Python 3.9+
- `bash` (already on macOS / Linux)

### Steps

```bash
# 1 — Clone or navigate to the project
cd browser-based-terminal

# 2 — Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3 — Install dependencies
pip install -r requirements.txt

# 4 — Start the server (default token: changeme-supersecret)
TERMINAL_TOKEN=my-secret uvicorn main:app --reload

# 5 — Open in browser
open http://localhost:8000
# Enter your token in the auth dialog, then enjoy the terminal!
```

**Optional environment variables:**

| Variable | Default | Description |
|---|---|---|
| `TERMINAL_TOKEN` | `changeme-supersecret` | Shared access token |
| `IDLE_TIMEOUT` | `600` | Idle session timeout in seconds |

---

## Running with Docker

```bash
# Build the image
docker build -t browser-terminal .

# Run (override the token via environment variable)
docker run -d \
  -p 8000:8000 \
  -e TERMINAL_TOKEN=my-super-secret \
  -e IDLE_TIMEOUT=600 \
  --name browser-terminal \
  browser-terminal

# Visit
open http://localhost:8000
```

---

## Security Considerations

> **Important for production deployments — this was intentionally designed with a threat model in mind.**

### Risks (and mitigations implemented)

| Risk | Mitigation |
|---|---|
| Unauthenticated shell access | Token validated on every WebSocket handshake (code 4001 on failure) |
| Idle sessions consuming resources | Configurable idle timeout kills PTY + closes socket |
| Runaway processes | `ptyprocess.terminate(force=True)` on disconnect |
| XSS via terminal output | xterm.js sanitises output; no `innerHTML` used |
| Token leakage in logs | Query params redacted from Uvicorn access logs (use `--no-access-log` in prod) |

### Additional hardening for production

1. **HTTPS / WSS** — Put behind nginx / Caddy with TLS; change `ws://` → `wss://`
2. **Namespacing / containers** — Run each session in a Docker container or Linux namespace (`unshare`) so users can't escape to the host
3. **Resource limits** — Use `ulimit` / cgroups to cap CPU, RAM, disk I/O per PTY
4. **Rate limiting** — Limit connection attempts per IP (e.g., via nginx `limit_req`)
5. **Non-root user** — Run the process (and bash) as an unprivileged user
6. **Read-only filesystem** — Mount most paths read-only; only allow writes to `/tmp`
7. **Audit logging** — Log every session's output for compliance / forensics
8. **Network isolation** — Sandbox the PTY network (no outbound internet from the shell)

---

## Project Structure

```
browser-based-terminal/
├── main.py          # FastAPI backend — WebSocket + PTY bridge
├── index.html       # Frontend — xterm.js terminal UI
├── requirements.txt # Python dependencies
├── Dockerfile       # Container definition
└── README.md        # You are here
```

---

## How It Compares to Production Systems

| Feature | This Project | Neverinstall / Gitpod |
|---|---|---|
| Real PTY | ✅ | ✅ |
| xterm.js frontend | ✅ | ✅ |
| WebSocket transport | ✅ | ✅ |
| Per-session isolation | ⚠️ Process-level | ✅ VM / container |
| Auth | ✅ Token-based | ✅ OAuth / SSO |
| Scaling | Single server | Kubernetes / cloud |

This project demonstrates the **exact same core mechanics** — the production difference is containerisation and orchestration, not the terminal protocol.
