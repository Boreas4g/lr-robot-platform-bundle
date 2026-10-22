"""车辆定距/缓速对齐服务的车端 HTTP 客户端（bookarm 侧）。

车端 robot_decision.vehicle_nudge_node 在 127.0.0.1:18091 暴露本机 HTTP 控制面；
定距移动由车端 /odom 反馈闭环停车，脉冲接口保留给旧调试工具。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict


class VehicleAlignClient:
    """127.0.0.1 本机车端定距对齐服务客户端。"""

    def __init__(self, base_url: str = "http://127.0.0.1:18091", timeout_s: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = float(timeout_s)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        url = self.base_url + path
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            self._raise_http_error(url, error)
        except (OSError, urllib.error.URLError, ValueError) as error:
            raise RuntimeError(
                "车辆对齐服务不可达（%s）：%s；请确认 lr-robot-runtime 已启动"
                % (self.base_url, error)
            ) from error
        if not data.get("ok", False):
            raise RuntimeError("车辆对齐服务拒绝执行：%s" % data.get("error", "未知原因"))
        return data

    @staticmethod
    def _raise_http_error(url: str, error: urllib.error.HTTPError) -> None:
        if error.code == 404:
            message = (
                "车辆对齐服务接口不存在（%s，HTTP 404）；运行中的 "
                "lr-robot-runtime 版本可能过旧，请从当前项目启动或重启"
            ) % url
        else:
            message = "车辆对齐服务返回 HTTP %s（%s）：%s" % (
                error.code,
                url,
                error.reason,
            )
        raise RuntimeError(message) from error

    def pulse(self, direction: str, duration_ms: int) -> Dict[str, Any]:
        """发一个定长缓速脉冲；direction: forward/backward。"""

        if direction not in ("forward", "backward"):
            raise ValueError("direction 必须为 forward/backward")
        return self._post("/pulse", {"direction": direction, "duration_ms": int(duration_ms)})

    def move_distance(self, direction: str, distance_m: float) -> Dict[str, Any]:
        """按指定距离移动，等待车端通过 /odom 确认停车后返回。"""

        if direction not in ("forward", "backward"):
            raise ValueError("direction 必须为 forward/backward")
        distance = float(distance_m)
        if distance <= 0.0:
            raise ValueError("distance_m 必须为正数")
        return self._post(
            "/move-distance",
            {"direction": direction, "distance_m": distance},
        )

    def stop(self) -> Dict[str, Any]:
        return self._post("/stop", {})

    def status(self) -> Dict[str, Any]:
        url = self.base_url + "/status"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            self._raise_http_error(url, error)
        except (OSError, urllib.error.URLError, ValueError) as error:
            raise RuntimeError(
                "车辆对齐服务不可达（%s）：%s；请确认 lr-robot-runtime 已启动"
                % (self.base_url, error)
            ) from error
