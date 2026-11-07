from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, session

MAX_BODY = 4096

_routes_state: dict = {"last": None}


def _authorized(header: str | None, expected: str) -> bool:
    if not expected:
        return False
    if not header or not header.startswith("Bearer "):
        return False
    supplied = header[len("Bearer ") :].strip()
    return hmac.compare_digest(supplied.encode(), expected.encode())


class Handler(BaseHTTPRequestHandler):
    server_version = "presence-guard"
    sys_version = ""
    token = ""
    cfg: config.Config

    def log_message(self, fmt: str, *args) -> None:
        # never log headers: they carry the bearer token
        print(f"[remote] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:
        if not _authorized(self.headers.get("Authorization"), self.token):
            self._send(401, {"error": "unauthorized"})
            return
        if self.path != "/status":
            self._send(404, {"error": "not found"})
            return
        self._send(
            200,
            {
                "locked": session.is_locked(),
                "session": session.session_id(),
                "last_guard_event": _routes_state["last"],
            },
        )

    def do_POST(self) -> None:
        if not _authorized(self.headers.get("Authorization"), self.token):
            self._send(401, {"error": "unauthorized"})
            return

        path = self.path.rstrip("/")
        if path == "/lock":
            try:
                detail = session.lock()
            except session.SessionError as exc:
                self._send(500, {"error": str(exc)})
                return
            _routes_state["last"] = "remote lock"
            self._send(200, {"action": "lock", "detail": detail})
            return

        if path == "/panic":
            if self._body().get("confirm") != "panic":
                self._send(400, {"error": 'confirmation required: {"confirm":"panic"}'})
                return
            try:
                lock_detail = session.lock()
            except session.SessionError as exc:
                self._send(500, {"error": str(exc)})
                return
            _routes_state["last"] = "remote panic"
            self._send(200, {"action": "panic", "lock": lock_detail, "poweroff": "requested"})
            # Answer first, then power off, so the phone sees a clean result.
            threading.Timer(1.5, _poweroff_safely).start()
            return

        self._send(404, {"error": "not found"})


def _poweroff_safely() -> None:
    try:
        session.poweroff()
    except session.SessionError as exc:
        print(f"[remote] poweroff failed: {exc}", flush=True)


def serve(cfg: config.Config | None = None) -> None:
    cfg = cfg or config.load()
    token = cfg.token
    if not token:
        raise SystemExit(
            f"no token at {cfg.remote.token_file}; create one with:\n"
            "  mkdir -p ~/.claude/secrets && head -c 32 /dev/urandom | base64 "
            f"> {cfg.remote.token_file} && chmod 600 {cfg.remote.token_file}"
        )
    Handler.token = token
    Handler.cfg = cfg
    server = ThreadingHTTPServer((cfg.remote.host, cfg.remote.port), Handler)
    print(f"[remote] listening on {cfg.remote.host}:{cfg.remote.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
