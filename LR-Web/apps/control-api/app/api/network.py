"""Authenticated Wi-Fi operations through a private host Unix socket."""

import http.client
import json
import socket
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ..config import get_settings
from ..dependencies import get_current_user
from ..schemas import User
from ..store import store


class NetworkRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Pydantic includes raw input in errors, potentially containing a PSK.
                return JSONResponse(
                    status_code=422,
                    content={"detail": "网络参数不合法，请检查网卡、Wi-Fi 名称、安全类型和切换确认选项"},
                )

        return validated


router = APIRouter(prefix="/api/v1/system/network", tags=["network"], route_class=NetworkRoute)


def network_operator(user: User = Depends(get_current_user)) -> User:
    if not get_settings().auth_enabled:
        raise HTTPException(503, "网络配置要求启用网站登录，请联系管理员")
    if user.role not in {"系统管理员", "维护人员", "图书馆操作员"}:
        raise HTTPException(403, "当前账号没有网络配置权限")
    return user


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interface: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,15}$")
    refresh: bool = False


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interface: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,15}$")
    request_id: UUID
    ssid: str | None = Field(default=None, min_length=1, max_length=32)
    password: SecretStr = Field(default_factory=lambda: SecretStr(""))
    security: Literal["open", "wpa-psk", "sae"] | None = None
    hidden: bool = False
    hotspot_uuid: UUID | None = None
    acknowledged: Literal[True]


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(get_settings().network_agent_socket)


def agent_request(method, path, payload=None):
    if not get_settings().network_agent_socket:
        raise HTTPException(503, "网络连接服务未配置，请联系管理员安装 lr-network-agent.service")
    connection = UnixConnection("localhost", timeout=20)
    try:
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        connection.request(method, path, body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("Oversized agent response")
        data = json.loads(raw)
        if response.status >= 400:
            raise HTTPException(
                response.status if response.status in {400, 403, 409, 413, 503} else 503,
                data.get("detail", "网络操作未成功"),
            )
        return data
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise HTTPException(503, "网络管理代理暂不可用，请检查 lr-network-agent.service") from error
    finally:
        connection.close()


@router.get("")
def network_status(_: User = Depends(network_operator)):
    return agent_request("GET", "/status")


@router.post("/scan")
def scan_networks(body: ScanRequest, _: User = Depends(network_operator)):
    return agent_request("POST", "/scan", body.model_dump())


@router.post("/connect", status_code=202)
def connect_network(body: ConnectRequest, _: User = Depends(network_operator)):
    # Queued and paused records can remain in history after the robot is idle.
    # Block only active execution, plus robot telemetry that indicates motion.
    if any(t.status == "running" for t in store.tasks) or any(
        r.status in {"busy", "mapping", "navigating", "manual"} for r in store.robots
    ):
        raise HTTPException(409, "机器人仍在执行作业、导航、手动控制或建图；请先停止机器人再切换网络")
    data = body.model_dump(mode="json", exclude={"password"}, exclude_none=True)
    data["password"] = body.password.get_secret_value()
    return agent_request("POST", "/connect", data)


@router.post("/confirm")
def confirm_network(body: ConfirmRequest, request: Request, _: User = Depends(network_operator)):
    # The port-8000 proxy replaces this header with its socket's real address.
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "请通过 8000 端口的控制页面确认连接")
    return agent_request(
        "POST", "/confirm", {"id": str(body.id), "local_address": request.headers.get("x-lr-local-address", "")}
    )
