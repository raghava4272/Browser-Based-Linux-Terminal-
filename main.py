"""
Browser-Based Linux Terminal — Backend
FastAPI + WebSocket + PTY (ptyprocess)

Architecture:
  Browser (xterm.js) ↔ WebSocket ↔ FastAPI ↔ PTY (bash)
"""

import asyncio
import json
import os
import logging

import ptyprocess
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Browser Terminal", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth helper ───────────────────────────────────────────────────────────────
SECRET_TOKEN = os.environ.get("TERMINAL_TOKEN", "changeme-supersecret")

IDLE_TIMEOUT_SECONDS = int(os.environ.get("IDLE_TIMEOUT", "600"))  # 10 min


# ── Serve index.html ──────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend HTML."""
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(index_path, "r") as f:
        return HTMLResponse(content=f.read())


# ── WebSocket terminal endpoint ───────────────────────────────────────────────
@app.websocket("/ws")
async def terminal_ws(websocket: WebSocket):
    """
    WebSocket endpoint for the terminal.

    Query param:  ?token=<SECRET_TOKEN>

    Protocol:
      • Raw bytes / text  → forward to PTY stdin
      • JSON { "type": "resize", "cols": N, "rows": N }  → resize PTY window
    """
    # ── 1. Authentication ─────────────────────────────────────────────────────
    token = websocket.query_params.get("token", "")
    if token != SECRET_TOKEN:
        await websocket.close(code=4001, reason="Unauthorized")
        logger.warning("Rejected WebSocket connection — bad token")
        return

    await websocket.accept()
    client = websocket.client
    logger.info("Terminal session opened for %s:%s", client.host, client.port)

    # ── 2. Spawn bash PTY ─────────────────────────────────────────────────────
    env = os.environ.copy()
    env.update(
        {
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "LANG": "en_US.UTF-8",
        }
    )

    try:
        pty_proc = ptyprocess.PtyProcess.spawn(
            ["bash", "--login"],
            env=env,
            dimensions=(24, 80),
        )
    except Exception as exc:
        logger.error("Failed to spawn PTY: %s", exc)
        await websocket.close(code=1011, reason="Failed to spawn shell")
        return

    logger.info("PTY spawned (pid=%d)", pty_proc.pid)

    # ── 3. Idle-timeout tracking ──────────────────────────────────────────────
    last_activity: list[float] = [asyncio.get_event_loop().time()]

    def touch():
        last_activity[0] = asyncio.get_event_loop().time()

    # ── 4. Concurrent tasks ───────────────────────────────────────────────────
    loop = asyncio.get_event_loop()

    async def ws_to_pty():
        """Read data from WebSocket → write to PTY stdin."""
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_text(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    # No data — check idle timeout
                    elapsed = asyncio.get_event_loop().time() - last_activity[0]
                    if elapsed >= IDLE_TIMEOUT_SECONDS:
                        logger.info(
                            "Session idle for %.0fs — disconnecting", elapsed
                        )
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_text(
                                "\r\n[Session timed out due to inactivity]\r\n"
                            )
                            await websocket.close(code=4002, reason="Idle timeout")
                        return
                    continue

                touch()

                # Check if it's a JSON control message
                try:
                    data = json.loads(message)
                    if data.get("type") == "resize":
                        cols = int(data.get("cols", 80))
                        rows = int(data.get("rows", 24))
                        cols = max(1, min(cols, 512))
                        rows = max(1, min(rows, 256))
                        pty_proc.setwinsize(rows, cols)
                        logger.debug("PTY resized → %dx%d", cols, rows)
                        continue
                except (json.JSONDecodeError, ValueError):
                    pass

                # Plain text/binary → forward to PTY
                if pty_proc.isalive():
                    await loop.run_in_executor(
                        None, pty_proc.write, message.encode("utf-8", errors="replace")
                    )

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected (ws_to_pty)")
        except Exception as exc:
            logger.error("ws_to_pty error: %s", exc)

    async def pty_to_ws():
        """Read PTY stdout → send to WebSocket."""
        try:
            while True:
                if not pty_proc.isalive():
                    logger.info("PTY process exited")
                    break
                try:
                    data: bytes = await loop.run_in_executor(
                        None, _read_pty, pty_proc
                    )
                    if data:
                        touch()
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_bytes(data)
                    else:
                        await asyncio.sleep(0.01)
                except EOFError:
                    logger.info("PTY EOF")
                    break
                except Exception as exc:
                    if "Input/output error" in str(exc) or "EIO" in str(exc):
                        logger.info("PTY closed (EIO)")
                        break
                    logger.error("pty_to_ws error: %s", exc)
                    break
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected (pty_to_ws)")
        finally:
            # Notify client that shell exited (if still connected)
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text("\r\n[Process completed — connection closed]\r\n")
                    await websocket.close(code=1000)
            except Exception:
                pass

    # ── 5. Run both tasks concurrently ────────────────────────────────────────
    try:
        task1 = asyncio.create_task(ws_to_pty())
        task2 = asyncio.create_task(pty_to_ws())
        done, pending = await asyncio.wait(
            [task1, task2], return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
    finally:
        # ── 6. Clean-up PTY ───────────────────────────────────────────────────
        if pty_proc.isalive():
            try:
                pty_proc.terminate(force=True)
            except Exception:
                pass
        logger.info(
            "Terminal session closed for %s:%s", client.host, client.port
        )


def _read_pty(pty_proc: ptyprocess.PtyProcess) -> bytes:
    """Blocking PTY read — runs in a thread-pool executor."""
    try:
        return pty_proc.read(4096)
    except EOFError:
        raise
    except OSError as exc:
        raise exc
