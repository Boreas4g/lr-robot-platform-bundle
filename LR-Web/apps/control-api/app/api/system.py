"""One-click platform startup/restart: run the curated fixed host scripts."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..dependencies import get_current_user
from ..config import get_settings
from ..schemas import User

router = APIRouter(prefix="/api/v1", tags=["system"])

START_ALL_OPERATION = "/v1/start-all"
RESTART_ALL_OPERATION = "/v1/restart-all"


def _default_script(script_name: str, configured: str | None, env_var: str) -> Path:
    """Find a host checkout without assuming the Docker image layout."""

    candidate_path = configured or os.environ.get(env_var)
    if candidate_path:
        return Path(candidate_path)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / script_name
        if candidate.is_file():
            return candidate
    return Path("/nonexistent") / script_name


START_ALL_SCRIPT = _default_script(
    "start-all.sh", get_settings().host_start_all_script, "LR_HOST_START_ALL_SCRIPT"
)
RESTART_ALL_SCRIPT = _default_script(
    "restart-all.sh", get_settings().host_restart_all_script, "LR_HOST_RESTART_ALL_SCRIPT"
)
SCRIPT_TIMEOUT_S = 240.0
HOST_AGENT_TIMEOUT_S = SCRIPT_TIMEOUT_S + 15.0


class StartAllStepView(BaseModel):
    """One component line reported by the fixed host script."""

    name: str
    status: str
    message: str


class StartAllView(BaseModel):
    """Aggregated result of one fixed-script run."""

    ok: bool
    steps: list[StartAllStepView] = Field(default_factory=list)
    output: str


def _parse_steps(output: str) -> list[StartAllStepView]:
    steps: list[StartAllStepView] = []
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=3)
        if len(parts) == 4 and parts[0] == "STEP":
            steps.append(StartAllStepView(name=parts[1], status=parts[2], message=parts[3]))
    return steps


def _request_host_start_agent(socket_path: str, operation: str) -> tuple[int, str]:
    """Call the host's fixed-command Unix-socket bridge.

    This protocol deliberately carries no command or parameters.  A compromised
    API process could at most request the same reviewed actions that a
    dashboard operator is already authorised to trigger.
    """

    request = (
        "POST %s HTTP/1.1\r\n" % operation
    ).encode("ascii") + (
        b"Host: lr-host-start-agent\r\n"
        b"Content-Length: 0\r\n"
        b"Connection: close\r\n\r\n"
    )
    chunks: list[bytes] = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(HOST_AGENT_TIMEOUT_S)
        client.connect(socket_path)
        client.sendall(request)
        while True:
            chunk = client.recv(64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    header, separator, body = raw.partition(b"\r\n\r\n")
    status_line = header.split(b"\r\n", 1)[0]
    if not separator or not status_line.startswith(b"HTTP/1.1 200 "):
        raise RuntimeError("宿主启动代理返回了无效响应")
    payload = json.loads(body.decode("utf-8"))
    return int(payload["returncode"]), str(payload["output"])


async def _run_fixed_script(script: Path, operation: str, label: str) -> tuple[int, str]:
    agent_socket = get_settings().host_start_agent_socket
    if agent_socket:
        try:
            return await asyncio.to_thread(_request_host_start_agent, agent_socket, operation)
        except (OSError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise HTTPException(
                status_code=503,
                detail=(
                    "宿主启动代理不可用；请检查 lr-host-start-agent.service。"
                    "容器不会直接操作宿主 CAN、systemd 或硬件。"
                ),
            ) from error
    if not script.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "当前 control-api 没有宿主启动代理；容器不能操作宿主 CAN、systemd 或硬件。"
                "请在宿主机运行 scripts/%s，或配置受控的宿主 agent。" % script.name
            ),
        )
    process = await asyncio.create_subprocess_exec(
        "bash",
        str(script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=SCRIPT_TIMEOUT_S)
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise HTTPException(status_code=504, detail="%s执行超时" % label) from error
    return process.returncode, stdout.decode("utf-8", errors="replace")


def _check_operator(user: User, label: str) -> None:
    # Single-operator debug mode intentionally keeps every operational action
    # open.  Authentication remains unchanged; role hardening is deferred.
    from ..store import store

    if not store.single_operator and user.role not in {"系统管理员", "图书馆操作员"}:
        raise HTTPException(status_code=403, detail="仅系统管理员可执行%s" % label)


def _build_view(returncode: int, output: str) -> StartAllView:
    steps = _parse_steps(output)
    failed = any(step.status == "FAILED" for step in steps)
    return StartAllView(ok=returncode == 0 and not failed, steps=steps, output=output)


@router.post("/system/start-all", response_model=StartAllView)
async def start_all(user: User = Depends(get_current_user)) -> StartAllView:
    _check_operator(user, "一键启动")
    returncode, output = await _run_fixed_script(START_ALL_SCRIPT, START_ALL_OPERATION, "一键启动")
    return _build_view(returncode, output)


@router.post("/system/restart-all", response_model=StartAllView)
async def restart_all(user: User = Depends(get_current_user)) -> StartAllView:
    _check_operator(user, "一键重启")
    returncode, output = await _run_fixed_script(
        RESTART_ALL_SCRIPT, RESTART_ALL_OPERATION, "一键重启"
    )
    return _build_view(returncode, output)


# ---------------------------------------------------------------------------
# BookArm startup-policy compatibility for older dashboard clients
# ---------------------------------------------------------------------------


class BookarmStartPolicyView(BaseModel):
    """Compatibility response; managed startup always includes the BookArm service."""

    allow: bool


def _read_bookarm_start_policy() -> BookarmStartPolicyView:
    return BookarmStartPolicyView(allow=True)


@router.get("/system/bookarm-start-policy", response_model=BookarmStartPolicyView)
def get_bookarm_start_policy(_: User = Depends(get_current_user)) -> BookarmStartPolicyView:
    return _read_bookarm_start_policy()


@router.put("/system/bookarm-start-policy", response_model=BookarmStartPolicyView)
def put_bookarm_start_policy(
    payload: BookarmStartPolicyView, user: User = Depends(get_current_user)
) -> BookarmStartPolicyView:
    _check_operator(user, "机械臂硬件启动确认")
    return BookarmStartPolicyView(allow=True)
