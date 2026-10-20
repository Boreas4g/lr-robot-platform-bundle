#!/usr/bin/env python3
"""End-to-end smoke test for the local LR control station.

Runs with the deployment virtualenv (LR-Web/.venv) and exercises the same
paths a browser would use: the static server on :8000, the FastAPI service on
:8080, PostgreSQL/Redis-backed state, MQTT command delivery and telemetry
ingestion, and the realtime WebSocket.

    LR-Web/.venv/bin/python deploy/local/smoke-test.py

The test creates and removes its own book / annotation / stress-template
records. The sample map MAP-302LAB is imported once and intentionally kept so
the UI has a map to display.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt
from websockets.sync.client import connect

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
CHECK = "\u2713"
CROSS = "\u2717"


class SmokeFailure(AssertionError):
    pass


class Runner:
    def __init__(self, web: str, mqtt_host: str, mqtt_port: int) -> None:
        self.web = web.rstrip("/")
        self.api = f"{self.web}/api/v1"
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.client = httpx.Client(timeout=30)
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, fn) -> None:
        try:
            detail = fn() or ""
            self.results.append((name, True, str(detail)))
            print(f"  {CHECK} {name} {detail}")
        except Exception as error:  # noqa: BLE001 - report every failure, keep going
            self.results.append((name, False, f"{type(error).__name__}: {error}"))
            print(f"  {CROSS} {name}: {type(error).__name__}: {error}")

    # -- helpers ---------------------------------------------------------
    def json(self, method: str, path: str, **kwargs):
        response = self.client.request(method, f"{self.api}{path}", **kwargs)
        if response.status_code >= 400:
            raise SmokeFailure(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
        return response

    def import_sample_map(self) -> str:
        maps = BUNDLE_ROOT / "LR-Web/external/Library_robot/maps"
        existing = {item["id"] for item in self.json("GET", "/library/maps").json()}
        if "MAP-302LAB" in existing:
            return "already imported"
        payload = {
            "id": "MAP-302LAB",
            "name": "302 实验室",
            "yamlName": "302lab.yaml",
            "yamlContent": base64.b64encode((maps / "302lab.yaml").read_bytes()).decode(),
            "pgmName": "302lab.pgm",
            "pgmContent": base64.b64encode((maps / "302lab.pgm").read_bytes()).decode(),
        }
        result = self.json("POST", "/library/maps/import", json=payload).json()
        return f"{result['id']} {result['width']}x{result['height']} @ {result['resolution']}m"

    def run(self) -> int:
        print(f"LR smoke test -> {self.web}")
        state: dict[str, str] = {}

        print("[station]")
        self.check("web /health proxied", lambda: self._health())
        self.check("current user", lambda: self._current_user())
        self.check("robots seeded", lambda: self._robots())

        print("[library]")
        self.check("sample map", lambda: self.import_sample_map())
        self.check("map preview PNG", lambda: self._preview())
        self.check("annotation create/list/patch", lambda: self._annotation(state))
        self.check("book create/update/list", lambda: self._book(state))
        self.check("stress template create", lambda: self._template(state))
        self.check("chassis params readable", lambda: self._chassis())
        self.check("battery snapshot", lambda: self._battery())
        self.check("battery realtime stream", lambda: self._battery_ws())
        self.check("bookarm policy", lambda: self._policy())

        print("[MQTT + realtime]")
        self.check("command delivered over MQTT", lambda: self._mqtt_command())
        self.check("telemetry reaches REST + WebSocket", lambda: self._telemetry())
        self.check("bookarm proxy / health sync", lambda: self._bookarm())

        self.cleanup(state)
        passed = sum(1 for _, ok, _ in self.results if ok)
        failed = len(self.results) - passed
        print(f"\n{passed} passed, {failed} failed")
        for name, ok, detail in self.results:
            if not ok:
                print(f"  FAILED {name}: {detail}")
        return 0 if failed == 0 else 1

    # -- checks ----------------------------------------------------------
    def _health(self):
        data = self.client.get(f"{self.web}/health", timeout=10).json()
        if data.get("status") != "ok":
            raise SmokeFailure(f"health={data}")
        deps = data.get("dependencies", {})
        for dep in ("postgres", "redis", "mqtt"):
            if deps.get(dep) != "connected":
                raise SmokeFailure(f"{dep}={deps.get(dep)}")
        return f"deps={deps}"

    def _current_user(self):
        data = self.json("GET", "/current-user").json()
        if not data.get("username"):
            raise SmokeFailure(f"unexpected user {data}")
        return data["username"]

    def _robots(self):
        robots = self.json("GET", "/robots").json()
        if not robots:
            raise SmokeFailure("no seeded robots")
        return ", ".join(f"{r['id']}:{r['status']}" for r in robots)

    def _preview(self):
        response = self.client.get(f"{self.api}/library/maps/MAP-302LAB/preview")
        if response.status_code != 200 or not response.content.startswith(b"\x89PNG"):
            raise SmokeFailure(f"status={response.status_code} bytes={len(response.content)}")
        return f"{len(response.content)} bytes"

    def _annotation(self, state: dict[str, str]):
        created = self.json(
            "POST",
            "/library/maps/MAP-302LAB/annotations",
            json={"kind": "shelf", "label": "冒烟测试书架", "pixelX": 100, "pixelY": 80, "yaw": 0.0},
        ).json()
        state["annotation"] = created["id"]
        listed = self.json("GET", "/library/maps/MAP-302LAB/annotations").json()
        if not any(item["id"] == created["id"] for item in listed):
            raise SmokeFailure("created annotation missing from list")
        updated = self.json(
            "PATCH",
            f"/library/maps/MAP-302LAB/annotations/{created['id']}",
            json={"label": "冒烟测试书架（改）", "x": 0.1, "y": 0.2, "yaw": 0.3},
        ).json()
        if updated["label"] != "冒烟测试书架（改）":
            raise SmokeFailure("patch did not apply")
        return f"{created['id']} -> map({updated['mapX']:.2f},{updated['mapY']:.2f})"

    def _book(self, state: dict[str, str]):
        created = self.json(
            "POST",
            "/books",
            json={"name": "冒烟测试图书", "templateId": "tpl-smoke", "heightMm": 230.0, "preferredSlot": 2},
        ).json()
        state["book"] = created["id"]
        updated = self.json(
            "PUT",
            f"/books/{created['id']}",
            json={"name": "冒烟测试图书（改）", "templateId": "tpl-smoke", "heightMm": 240.0, "preferredSlot": 3},
        ).json()
        if updated["heightMm"] != 240.0:
            raise SmokeFailure("book update did not apply")
        listed = self.json("GET", "/books").json()
        if not any(item["id"] == created["id"] for item in listed):
            raise SmokeFailure("created book missing from list")
        return f"{created['id']} {len(listed)} book(s)"

    def _template(self, state: dict[str, str]):
        if "book" not in state:
            raise SmokeFailure("book creation failed earlier")
        created = self.json(
            "POST",
            "/debug/stress-test/templates",
            json={
                "name": "冒烟模板",
                "config": {
                    "takeouts": [{"bookId": state["book"], "destinationSlot": 2}],
                    "returns": [],
                    "liftSpeedLevel": 2,
                    "maxRounds": 1,
                    "stopOnFailure": True,
                },
            },
        ).json()
        state["template"] = created["id"]
        return created["id"]

    def _chassis(self):
        params = self.json("GET", "/debug/chassis-params").json().get("params", [])
        if not params:
            raise SmokeFailure("no chassis params returned")
        unavailable = [item for item in params if not item.get("available")]
        if any(not item.get("unavailable_reason") for item in unavailable):
            raise SmokeFailure("unavailable params must explain why")
        return f"{len(params) - len(unavailable)}/{len(params)} params available"

    def _battery(self):
        data = self.json("GET", "/power/battery").json()
        if "source" not in data:
            raise SmokeFailure(f"unexpected battery payload {data}")
        return f"status={data['status']} source={data['source']}"

    def _battery_ws(self):
        ws = connect(
            f"ws{'s' if self.web.startswith('https') else ''}://{self.web.split('://', 1)[1]}/api/v1/realtime/battery",
            open_timeout=10,
            legacy=True,
        )
        try:
            frame = json.loads(ws.recv(timeout=10))
            if frame.get("type") != "battery.updated":
                raise SmokeFailure(f"unexpected battery frame {frame.get('type')}")
            return f"status={frame['battery']['status']}"
        finally:
            ws.close()

    def _policy(self):
        data = self.json("GET", "/system/bookarm-start-policy").json()
        return f"allow={data.get('allow')}"

    def _mqtt_command(self):
        received: list[dict] = []

        def on_message(_client, _userdata, message):
            received.append(json.loads(message.payload.decode("utf-8")))

        subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"smoke-sub-{uuid.uuid4().hex[:8]}")
        subscriber.on_message = on_message
        subscriber.connect(self.mqtt_host, self.mqtt_port, 30)
        subscriber.subscribe("fleet/+/command", qos=1)
        subscriber.loop_start()
        try:
            time.sleep(0.5)
            key = f"smoke-{uuid.uuid4().hex}"
            first = self.json(
                "POST",
                "/robots/LR-01/commands",
                json={"command": "stop", "payload": {}, "idempotencyKey": key},
            ).json()
            time.sleep(1.0)
            second = self.json(
                "POST",
                "/robots/LR-01/commands",
                json={"command": "stop", "payload": {}, "idempotencyKey": key},
            ).json()
            if first["commandId"] != second["commandId"]:
                raise SmokeFailure("idempotency key returned a different command")
            if not received:
                raise SmokeFailure("no MQTT command received")
            published = received[0]
            if published.get("commandId") != first["commandId"]:
                raise SmokeFailure("MQTT payload does not match command")
            if published.get("issuedBy") != "operator":
                raise SmokeFailure(f"unexpected issuer {published.get('issuedBy')}")
            return f"{first['commandId']} published once, duplicate suppressed"
        finally:
            subscriber.loop_stop()
            subscriber.disconnect()

    def _telemetry(self):
        ws = connect(
            f"ws{'s' if self.web.startswith('https') else ''}://{self.web.split('://', 1)[1]}/api/v1/realtime/robots",
            open_timeout=10,
            legacy=True,
        )
        try:
            snapshot = json.loads(ws.recv(timeout=10))
            if snapshot.get("type") != "robots.snapshot":
                raise SmokeFailure(f"unexpected first frame {snapshot.get('type')}")
            telemetry = {
                "robotId": "LR-01",
                "frameId": "map",
                "mapId": "MAP-302LAB",
                "nav2Ready": True,
                "chassisReady": True,
                "x": 1.23,
                "y": 3.45,
                "yaw": 0.5,
                "localizationStatus": "localized",
                "localizationScanMode": "dual",
                "imuReady": True,
                "armReady": False,
                "rodReady": False,
                "liftReady": False,
                "cameraReady": False,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"smoke-pub-{uuid.uuid4().hex[:8]}")
            publisher.connect(self.mqtt_host, self.mqtt_port, 30)
            publisher.loop_start()
            try:
                info = publisher.publish("fleet/LR-01/telemetry", json.dumps(telemetry), qos=0)
                info.wait_for_publish(timeout=5)
            finally:
                publisher.loop_stop()
                publisher.disconnect()

            update = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                frame = json.loads(ws.recv(timeout=deadline - time.monotonic()))
                robot = frame.get("robot") or {}
                if frame.get("type") == "robot.updated" and robot.get("mapId") == "MAP-302LAB":
                    update = robot
                    break
            if not update:
                raise SmokeFailure("no robot.updated frame for MAP-302LAB")
            pose = update.get("pose") or {}
            if abs(pose.get("x", 0) - 1.23) > 1e-6:
                raise SmokeFailure(f"pose not applied: {pose}")
            rest = self.json("GET", "/robots").json()[0]
            if rest.get("mapId") != "MAP-302LAB":
                raise SmokeFailure("telemetry not persisted to REST summary")
            return f"pose=({pose['x']},{pose['y']},{pose['yaw']}) via WS"
        finally:
            ws.close()

    def _bookarm(self):
        """Accept an absent BookArm service, or verify the fake one is wired in."""
        response = self.client.get(f"{self.web}/bookarm-api/v1/takeout/health", timeout=10)
        if response.status_code >= 500:
            return f"offline (HTTP {response.status_code}) - expected without a service"
        if response.status_code != 200:
            raise SmokeFailure(f"unexpected proxy response {response.status_code}: {response.text[:200]}")
        health = response.json()
        mode = health.get("mode", "unknown")
        if mode != "fake":
            return f"service reachable, mode={mode}"
        # The fake service proves the Unix socket path is shared with control-api:
        # its health poller must flip rod/lift/camera within a few seconds.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            robot = self.json("GET", "/robots").json()[0]
            flags = robot.get("health", {})
            if flags.get("rod") and flags.get("lift") and flags.get("camera"):
                return "fake mode, station health synced (rod/lift/camera)"
            time.sleep(1)
        raise SmokeFailure("fake BookArm reachable but control-api health did not sync")

    def cleanup(self, state: dict[str, str]) -> None:
        for key, path in (
            ("template", "/debug/stress-test/templates/{id}"),
            ("book", "/books/{id}"),
            ("annotation", "/library/maps/MAP-302LAB/annotations/{id}"),
        ):
            if key not in state:
                continue
            try:
                self.client.delete(f"{self.api}{path.format(id=state[key])}")
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", default="http://127.0.0.1:8000")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=51883)
    args = parser.parse_args()
    try:
        return Runner(args.web, args.mqtt_host, args.mqtt_port).run()
    except httpx.HTTPError as error:
        print(f"cannot reach {args.web}: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
