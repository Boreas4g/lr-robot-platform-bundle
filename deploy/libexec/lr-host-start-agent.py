#!/usr/bin/env python3
"""A deliberately narrow host-side bridge for the dashboard start button.

The containerised control-api has no host privileges.  This process is the
only bridge it receives: it accepts two fixed HTTP requests on a private Unix
socket and runs the matching fixed, reviewed script.  It never accepts a
command, arguments, environment values, or arbitrary paths from the caller.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import threading
from http import HTTPStatus
from pathlib import Path
from socketserver import BaseRequestHandler, ThreadingUnixStreamServer


DEFAULT_SCRIPT = "/home/boreas/lr-robot-platform-bundle/LR-Web/scripts/start-all.sh"
DEFAULT_RESTART_SCRIPT = "/home/boreas/lr-robot-platform-bundle/LR-Web/scripts/restart-all.sh"
MAX_REQUEST_BYTES = 8 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
START_TIMEOUT_SECONDS = 250


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LR fixed-command host start agent")
    parser.add_argument("--socket", required=True, help="private Unix socket path")
    parser.add_argument(
        "--script",
        default=DEFAULT_SCRIPT,
        help="reviewed start-all script path (configured by the service unit only)",
    )
    parser.add_argument(
        "--restart-script",
        default=DEFAULT_RESTART_SCRIPT,
        help="reviewed restart-all script path (configured by the service unit only)",
    )
    return parser.parse_args()


class StartAllAgent(ThreadingUnixStreamServer):
    """Unix server whose sole capability is serialised fixed-script execution."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, socket_path: str, script_path: Path, restart_script_path: Path) -> None:
        self.script_path = script_path.resolve()
        self.restart_script_path = restart_script_path.resolve()
        self.start_lock = threading.Lock()
        super().__init__(socket_path, StartAllHandler)
        os.chmod(socket_path, 0o660)

    def run_start_all(self) -> tuple[int, str]:
        return self._run_fixed_script(self.script_path, "一键启动")

    def run_restart_all(self) -> tuple[int, str]:
        return self._run_fixed_script(self.restart_script_path, "一键重启")

    def _run_fixed_script(self, script_path: Path, label: str) -> tuple[int, str]:
        if not script_path.is_file():
            return 127, "宿主%s脚本不存在：%s" % (label, script_path)
        if not os.access(script_path, os.R_OK):
            return 126, "宿主%s脚本不可读：%s" % (label, script_path)

        with self.start_lock:
            process = subprocess.Popen(
                ["/usr/bin/bash", str(script_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                stdout, _ = process.communicate(timeout=START_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    stdout, _ = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, _ = process.communicate()
                return 124, (stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") + "\n%s超时" % label)

        output = stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        if len(stdout) > MAX_OUTPUT_BYTES:
            output += "\n输出过长，已截断。"
        return process.returncode, output


class StartAllHandler(BaseRequestHandler):
    server: StartAllAgent

    def handle(self) -> None:
        request = self.request.recv(MAX_REQUEST_BYTES + 1)
        if len(request) > MAX_REQUEST_BYTES:
            self.respond(HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE, {"detail": "请求过长"})
            return
        header, _, body = request.partition(b"\r\n\r\n")
        request_line = header.split(b"\r\n", 1)[0]
        if body or request_line not in (b"POST /v1/start-all HTTP/1.1", b"POST /v1/restart-all HTTP/1.1"):
            self.respond(HTTPStatus.NOT_FOUND, {"detail": "仅支持固定的 POST /v1/start-all 与 POST /v1/restart-all 操作"})
            return
        if request_line == b"POST /v1/restart-all HTTP/1.1":
            returncode, output = self.server.run_restart_all()
        else:
            returncode, output = self.server.run_start_all()
        self.respond(HTTPStatus.OK, {"returncode": returncode, "output": output})

    def respond(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = (
            "HTTP/1.1 %d %s\r\n" % (status.value, status.phrase)
        ).encode("ascii")
        response += b"Content-Type: application/json; charset=utf-8\r\n"
        response += b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body)
        self.request.sendall(response + body)


def main() -> int:
    args = parse_args()
    socket_path = Path(args.socket)
    script_path = Path(args.script)
    restart_script_path = Path(args.restart_script)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists() or socket_path.is_symlink():
        if not socket_path.is_socket():
            raise RuntimeError("refusing to replace non-socket path: %s" % socket_path)
        socket_path.unlink()
    with StartAllAgent(str(socket_path), script_path, restart_script_path) as server:
        server.serve_forever(poll_interval=0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
