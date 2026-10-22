"""车辆低速移动节点：为 bookarm 识别后居中校正提供本机 HTTP 控制面。

bookarm 任务在升降杆高位时需要前后微量动车（取/还书对齐目标书）。
本节点只监听 127.0.0.1（默认端口 18091），对外仅有三个端点：

  POST /pulse {"direction": "forward"|"backward", "duration_ms": int}
  POST /move-distance {"direction": "forward"|"backward", "distance_m": float}
  POST /stop
  GET  /status

安全特性（升降杆高位场景）：
  - 空闲时不发布速度；定距/脉冲结束归零后只发送一次停车，不干扰手控或导航；
  - 发布端斜坡：定时器以 accel 限步逼近目标速度，到点/停止同样斜坡归零，
    缓启动缓停；底盘驱动层 accel_rpm_per_sec 是第二层兜底；
  - 速度硬上限 hard_speed_cap（默认 0.08 m/s），脉冲目标速度默认 0.03 m/s；
  - 单次里程计定距上限 max_move_distance_m（默认 20cm），旧脉冲时长上限 500ms；
  - 脉冲模式看门狗：watchdog_ms 内无新指令立即归零；定距模式另检 odom 超时；
  - 定距移动检查 /odom 新鲜度、方向和停滞；行程闸累计里程超限后冷却。
"""

import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
except ImportError as error:  # ROS 环境未 source 时直接失败，由 systemd 重启
    import sys

    print(f"vehicle_nudge_node: 无法导入 rclpy（ROS 环境未 source？）: {error}", file=sys.stderr)
    raise SystemExit(1)


def _ramp_toward(current: float, target: float, step: float) -> float:
    if current < target:
        return min(current + step, target)
    return max(current - step, target)


class VehicleNudgeCore:
    """ROS 节点 + 斜坡脉冲执行体。"""

    HARD_MOVE_DISTANCE_CAP_M = 0.20

    def __init__(self) -> None:
        self.node = rclpy.create_node("vehicle_nudge_node")
        self.pulse_speed = float(self.node.declare_parameter("pulse_speed", 0.03).value)
        self.accel = float(self.node.declare_parameter("accel", 0.12).value)
        self.rate_hz = float(self.node.declare_parameter("rate_hz", 20.0).value)
        self.hard_speed_cap = float(self.node.declare_parameter("hard_speed_cap", 0.08).value)
        self.max_pulse_ms = int(self.node.declare_parameter("max_pulse_ms", 500).value)
        self.watchdog_ms = int(self.node.declare_parameter("watchdog_ms", 800).value)
        self.travel_cap_m = float(self.node.declare_parameter("travel_cap_m", 0.25).value)
        configured_move_cap = float(
            self.node.declare_parameter("max_move_distance_m", 0.20).value
        )
        self.max_move_distance_m = (
            min(configured_move_cap, self.HARD_MOVE_DISTANCE_CAP_M)
            if math.isfinite(configured_move_cap) and configured_move_cap > 0.0
            else 0.0
        )
        self.odom_timeout_s = float(self.node.declare_parameter("odom_timeout_s", 0.5).value)
        self.move_distance_tolerance_m = float(
            self.node.declare_parameter("move_distance_tolerance_m", 0.002).value
        )
        self.travel_cooldown_s = float(
            self.node.declare_parameter("travel_cooldown_s", 60.0).value
        )

        self.pulse_speed = min(max(self.pulse_speed, 0.005), self.hard_speed_cap)

        self._lock = threading.Lock()
        self._target_linear = 0.0
        self._out_linear = 0.0
        self._last_published_nonzero = False
        self._deadline = 0.0  # time.monotonic()；脉冲结束时刻
        self._commanded_at = 0.0  # 最近一次任何指令的时间；0=从未
        self._travel_m = 0.0
        self._travel_locked_until = 0.0
        self._last_tick = time.monotonic()
        self._move_condition = threading.Condition(self._lock)
        self._move_state = None
        self._latest_odom = None
        self._latest_odom_at = 0.0

        self._cmd_pub = self.node.create_publisher(Twist, "/cmd_vel", 10)
        self._odom_sub = self.node.create_subscription(
            Odometry, "/odom", self._odom_callback, 10
        )
        self._timer = self.node.create_timer(1.0 / self.rate_hz, self._on_timer)
        self._spin_thread = threading.Thread(target=self._spin, name="nudge-spin", daemon=True)
        self._spin_thread.start()
        self.node.get_logger().info(
            "vehicle_nudge_node 就绪：speed=%.3f m/s accel=%.2f m/s² cap=%.2f m odom=/odom"
            % (self.pulse_speed, self.accel, self.travel_cap_m)
        )

    @staticmethod
    def _odom_pose(message: Odometry) -> tuple[float, float, float]:
        position = message.pose.pose.position
        orientation = message.pose.pose.orientation
        sin_yaw = 2.0 * (orientation.w * orientation.z + orientation.x * orientation.y)
        cos_yaw = 1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z)
        return float(position.x), float(position.y), math.atan2(sin_yaw, cos_yaw)

    def _odom_callback(self, message: Odometry) -> None:
        pose = self._odom_pose(message)
        with self._move_condition:
            self._latest_odom = pose
            self._latest_odom_at = time.monotonic()
            self._move_condition.notify_all()

    def _move_progress_locked(self) -> float:
        state = self._move_state
        if state is None or self._latest_odom is None:
            return 0.0
        x, y, _yaw = self._latest_odom
        dx = x - state["start_x"]
        dy = y - state["start_y"]
        return state["direction_sign"] * (
            dx * math.cos(state["start_yaw"]) + dy * math.sin(state["start_yaw"])
        )

    def _finish_move_locked(self, ok: bool, error: str | None = None) -> None:
        state = self._move_state
        if state is None:
            return
        self._target_linear = 0.0
        state["phase"] = "done"
        state["result"] = {
            "ok": bool(ok),
            "direction": state["direction"],
            "requested_distance_m": round(state["target_distance_m"], 4),
            "travelled_distance_m": round(max(0.0, self._move_progress_locked()), 4),
            "error_m": round(
                state["target_distance_m"] - max(0.0, self._move_progress_locked()), 4
            ),
            "duration_s": round(time.monotonic() - state["started_at"], 3),
        }
        if error:
            state["result"]["error"] = error
        self._move_condition.notify_all()

    def _update_distance_move_locked(self, now: float) -> None:
        state = self._move_state
        if state is None or state["phase"] == "done":
            return
        if self._latest_odom is None or now - self._latest_odom_at > self.odom_timeout_s:
            state["phase"] = "stopping_error"
            state["error"] = "里程计 /odom 超时，已停止定距移动"
            self._target_linear = 0.0
            return
        progress = self._move_progress_locked()
        state["progress_m"] = progress
        if progress < -0.02:
            state["phase"] = "stopping_error"
            state["error"] = "里程计显示底盘向错误方向移动，已停止"
            self._target_linear = 0.0
            return
        if progress > state["last_progress_m"] + 0.001:
            state["last_progress_m"] = progress
            state["last_progress_at"] = now
        elif now - state["last_progress_at"] > 2.0 and self._out_linear > 0.005:
            state["phase"] = "stopping_error"
            state["error"] = "底盘运动期间里程计距离没有增加，已停止"
            self._target_linear = 0.0
            return
        if progress > state["last_travel_progress_m"]:
            self._travel_m += progress - state["last_travel_progress_m"]
            state["last_travel_progress_m"] = progress
            if self._travel_m >= self.travel_cap_m:
                self._travel_locked_until = now + self.travel_cooldown_s
                state["phase"] = "stopping_error"
                state["error"] = "车辆居中累计里程达到安全上限，已停止"
                self._target_linear = 0.0
                return
        if now >= state["deadline"]:
            state["phase"] = "stopping_error"
            state["error"] = "定距移动超时，已停止"
            self._target_linear = 0.0
            return

        remaining = state["target_distance_m"] - max(0.0, progress)
        if state["phase"] == "stopping_error":
            self._target_linear = 0.0
            return
        if state["phase"] == "stopping":
            self._target_linear = 0.0
            return
        braking_distance = (
            self._out_linear * self._out_linear / max(2.0 * self.accel, 1e-6)
            + abs(self._out_linear) / max(self.rate_hz, 1.0)
        )
        if remaining <= max(self.move_distance_tolerance_m, braking_distance):
            state["phase"] = "stopping"
            self._target_linear = 0.0
            return
        desired_speed = min(
            self.pulse_speed,
            math.sqrt(max(0.0, 2.0 * self.accel * remaining)),
        )
        self._target_linear = state["direction_sign"] * desired_speed

    def _spin(self) -> None:
        try:
            rclpy.spin(self.node)
        except Exception:
            pass

    def _on_timer(self) -> None:
        now = time.monotonic()
        with self._move_condition:
            dt = max(now - self._last_tick, 1e-3)
            self._last_tick = now
            step = self.accel / self.rate_hz
            moving_distance = self._move_state is not None and self._move_state["phase"] != "done"
            if moving_distance:
                self._update_distance_move_locked(now)
                self._out_linear = _ramp_toward(self._out_linear, self._target_linear, step)
            else:
                expired = now >= self._deadline
                stale = (
                    self._commanded_at > 0.0
                    and (now - self._commanded_at) * 1000.0 > self.watchdog_ms
                )
                if stale:
                    # 脉冲接口看门狗：立即零速，不走斜坡。
                    self._out_linear = 0.0
                    self._target_linear = 0.0
                    self._deadline = 0.0
                elif expired:
                    self._target_linear = 0.0
                    self._out_linear = _ramp_toward(self._out_linear, 0.0, step)
                else:
                    self._out_linear = _ramp_toward(self._out_linear, self._target_linear, step)
            if not moving_distance:
                self._travel_m += abs(self._out_linear) * dt
            linear = self._out_linear
            if linear != 0.0 or self._last_published_nonzero:
                message = Twist()
                message.linear.x = linear
                try:
                    self._cmd_pub.publish(message)
                except Exception:
                    # Keep a pending stop if publishing fails; retry on the next tick.
                    return
                self._last_published_nonzero = linear != 0.0
            state = self._move_state
            if state is not None and state["phase"] != "done" and self._out_linear == 0.0:
                if state["phase"] == "stopping_error":
                    self._finish_move_locked(False, state.get("error"))
                elif state["phase"] == "stopping":
                    progress = max(0.0, self._move_progress_locked())
                    overshoot_limit = max(0.01, self.move_distance_tolerance_m * 3.0)
                    if progress > state["target_distance_m"] + overshoot_limit:
                        self._finish_move_locked(False, "里程计检测到定距移动超程，已停车")
                    elif progress >= state["target_distance_m"] - self.move_distance_tolerance_m:
                        self._finish_move_locked(True)
                    else:
                        # 斜坡停车后仍略短时，再以里程计余量启动一小段。
                        state["phase"] = "moving"

    # -- 对外操作 -----------------------------------------------------------

    def pulse(self, direction: str, duration_ms: int) -> dict:
        if direction not in ("forward", "backward"):
            return {"ok": False, "error": "direction 必须为 forward/backward"}
        duration_ms = int(duration_ms)
        if duration_ms <= 0:
            return {"ok": False, "error": "duration_ms 必须为正"}
        if duration_ms > self.max_pulse_ms:
            return {"ok": False, "error": "duration_ms 超过单脉冲上限 %d ms" % self.max_pulse_ms}
        now = time.monotonic()
        with self._move_condition:
            if (
                self._move_state is not None
                or abs(self._target_linear) > 1e-6
                or abs(self._out_linear) > 1e-6
            ):
                return {"ok": False, "error": "定距移动执行中，拒绝并发脉冲"}
            if now < self._travel_locked_until:
                return {
                    "ok": False,
                    "error": "行程闸冷却中（累计 %.3f m ≥ %.2f m），%.0fs 后解除"
                    % (self._travel_m, self.travel_cap_m, self._travel_locked_until - now),
                }
            sign = 1.0 if direction == "forward" else -1.0
            self._target_linear = sign * self.pulse_speed
            self._deadline = now + duration_ms / 1000.0
            self._commanded_at = now
            travel = self._travel_m
        return {
            "ok": True,
            "direction": direction,
            "duration_ms": duration_ms,
            "speed_mps": self.pulse_speed,
            "travel_m_est": round(travel, 4),
        }

    def move_distance(self, direction: str, distance_m: float) -> dict:
        """Move straight until fresh /odom reports the requested distance."""
        if direction not in ("forward", "backward"):
            return {"ok": False, "error": "direction 必须为 forward/backward"}
        try:
            distance_m = float(distance_m)
        except (TypeError, ValueError):
            return {"ok": False, "error": "distance_m 必须为有效数字"}
        if not math.isfinite(distance_m) or distance_m <= 0.0:
            return {"ok": False, "error": "distance_m 必须为正数"}
        if distance_m <= self.move_distance_tolerance_m:
            return {
                "ok": False,
                "error": "distance_m 不大于里程计停车容差 %.3f m" % self.move_distance_tolerance_m,
            }
        if distance_m > self.max_move_distance_m:
            return {
                "ok": False,
                "error": "distance_m 超过单次定距上限 %.3f m" % self.max_move_distance_m,
            }

        now = time.monotonic()
        with self._move_condition:
            if (
                self._move_state is not None
                or abs(self._target_linear) > 1e-6
                or abs(self._out_linear) > 1e-6
            ):
                return {"ok": False, "error": "车辆当前正在执行其他移动指令"}
            if self._latest_odom is None or now - self._latest_odom_at > self.odom_timeout_s:
                return {"ok": False, "error": "里程计 /odom 不可用或数据已过期，拒绝动车"}
            if now < self._travel_locked_until:
                return {
                    "ok": False,
                    "error": "行程闸冷却中（累计 %.3f m ≥ %.2f m），%.0fs 后解除"
                    % (self._travel_m, self.travel_cap_m, self._travel_locked_until - now),
                }
            start_x, start_y, start_yaw = self._latest_odom
            direction_sign = 1.0 if direction == "forward" else -1.0
            timeout_s = max(4.0, distance_m / max(self.pulse_speed, 0.005) * 5.0 + 2.0)
            self._move_state = {
                "direction": direction,
                "direction_sign": direction_sign,
                "target_distance_m": distance_m,
                "start_x": start_x,
                "start_y": start_y,
                "start_yaw": start_yaw,
                "started_at": now,
                "deadline": now + timeout_s,
                "last_progress_m": 0.0,
                "last_travel_progress_m": 0.0,
                "last_progress_at": now,
                "phase": "moving",
                "result": None,
            }
            self._target_linear = direction_sign * self.pulse_speed
            self._deadline = 0.0
            self._commanded_at = now

            while self._move_state["phase"] != "done":
                self._move_condition.wait(timeout=0.2)
            result = dict(self._move_state["result"])
            self._move_state = None
            self._target_linear = 0.0
            return result

    def stop(self) -> dict:
        with self._move_condition:
            if self._move_state is not None and self._move_state["phase"] != "done":
                self._move_state["phase"] = "stopping_error"
                self._move_state["error"] = "收到停车指令，定距移动已取消"
            self._target_linear = 0.0
            self._deadline = 0.0
            self._commanded_at = time.monotonic()
            self._move_condition.notify_all()
        return {"ok": True}

    def status(self) -> dict:
        with self._move_condition:
            payload = {
                "ok": True,
                "moving": (
                    abs(self._target_linear) > 1e-6 or abs(self._out_linear) > 1e-6
                ),
                "out_linear": round(self._out_linear, 4),
                "travel_m_est": round(self._travel_m, 4),
                "travel_locked": time.monotonic() < self._travel_locked_until,
                "pulse_speed": self.pulse_speed,
                "accel": self.accel,
                "odom_available": (
                    self._latest_odom is not None
                    and time.monotonic() - self._latest_odom_at <= self.odom_timeout_s
                ),
            }
            if self._move_state is not None:
                payload["move_distance_m"] = self._move_state["target_distance_m"]
                payload["move_progress_m"] = round(self._move_progress_locked(), 4)
            return payload

    def _check_travel_gate(self) -> None:
        """定时器内检查行程闸：超限即锁定并冷却。"""
        with self._move_condition:
            if self._travel_m >= self.travel_cap_m and self._travel_locked_until == 0.0:
                self._travel_locked_until = time.monotonic() + self.travel_cooldown_s
                self._target_linear = 0.0
                self._deadline = 0.0
                if self._move_state is not None and self._move_state["phase"] != "done":
                    self._move_state["phase"] = "stopping_error"
                    self._move_state["error"] = "车辆居中累计行程达到安全上限，已停止"
                self.node.get_logger().warn("行程闸触发：冷却 %.0fs" % self.travel_cooldown_s)
                self._move_condition.notify_all()
            elif self._travel_locked_until and time.monotonic() >= self._travel_locked_until:
                self._travel_locked_until = 0.0
                self._travel_m = 0.0
                self.node.get_logger().info("行程闸冷却结束，计数清零")


class _Handler(BaseHTTPRequestHandler):
    server_version = "lr-vehicle-nudge/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib 签名
        return

    def _reply(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib 签名
        if self.path == "/status":
            self._reply(self.server.core.status())
        else:
            self._reply({"ok": False, "error": "未知端点"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib 签名
        if self.path == "/stop":
            self._reply(self.server.core.stop())
            return
        if self.path not in ("/pulse", "/move-distance"):
            self._reply({"ok": False, "error": "未知端点"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            direction = payload["direction"]
            if self.path == "/pulse":
                duration_ms = payload["duration_ms"]
            else:
                distance_m = payload["distance_m"]
        except (ValueError, KeyError, TypeError):
            required = "direction/duration_ms" if self.path == "/pulse" else "direction/distance_m"
            self._reply({"ok": False, "error": "请求体须为 JSON 且含 %s" % required}, 400)
            return
        if self.path == "/pulse":
            result = self.server.core.pulse(direction, duration_ms)
        else:
            result = self.server.core.move_distance(direction, distance_m)
        self._reply(result)


def main() -> int:
    rclpy.init(args=None)
    core = VehicleNudgeCore()

    node = core.node
    host = str(node.declare_parameter("host", "127.0.0.1").value)
    port = int(node.declare_parameter("port", 18091).value)

    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.core = core  # type: ignore[attr-defined]
    node.get_logger().info(f"HTTP 控制面监听 http://{host}:{port}")

    # 行程闸在 1Hz 慢线程里检查
    def _gate_loop() -> None:
        while True:
            core._check_travel_gate()
            time.sleep(1.0)

    threading.Thread(target=_gate_loop, name="travel-gate", daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        core.stop()
        httpd.server_close()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
