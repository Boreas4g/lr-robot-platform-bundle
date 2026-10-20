#!/usr/bin/env python3
"""Hardware-free takeout → mid-return workflow test.

Requires the fake BookArm service (deploy/local/start-bookarm-fake.sh) and the
running control station. It uploads a synthetic spine image through the web
proxy, registers a temporary robot, injects one telemetry frame to bring that
robot online, then drives complete-takeout and complete-mid-return through the
control API and waits for both tasks to complete.

    bash deploy/local/start-bookarm-fake.sh          # optional service
    LR-Web/.venv/bin/python deploy/local/workflow-test.py

The temporary robot and spine template are removed afterwards. The two
completed task rows remain visible in 任务调度 as an audit trail.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime

import cv2
import httpx
import numpy as np
import paho.mqtt.client as mqtt

ROBOT_ID = "LR-SMOKE"
MAP_ID = "MAP-302LAB"


def make_spine_image() -> bytes:
    image = np.full((600, 140, 3), 235, np.uint8)
    cv2.rectangle(image, (15, 20), (125, 580), (90, 120, 180), -1)
    for index in range(12):
        cv2.line(image, (25, 60 + index * 40), (115, 60 + index * 40), (230, 230, 230), 2)
    cv2.putText(image, "LR", (35, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("could not encode synthetic spine image")
    return buffer.tobytes()


def poll_task(client: httpx.Client, api: str, task_id: str, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        tasks = client.get(f"{api}/dispatch/tasks", timeout=15).json()
        task = next((item for item in tasks if item["id"] == task_id), None)
        if task is not None:
            last = task
            if task["status"] in {"completed", "failed", "cancelled", "recovery_required"}:
                return task
        time.sleep(1)
    raise TimeoutError(f"task {task_id} did not finish in {timeout_s}s; last={json.dumps(last, ensure_ascii=False)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", default="http://127.0.0.1:8000")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=51883)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    api = f"{args.web.rstrip('/')}/api/v1"
    bookarm = f"{args.web.rstrip('/')}/bookarm-api/v1"
    client = httpx.Client(timeout=30)
    template_id: str | None = None
    robot_created = False
    failures: list[str] = []

    def step(name: str, fn):
        try:
            detail = fn()
            print(f"  \u2713 {name} {detail or ''}")
            return True
        except Exception as error:  # noqa: BLE001 - keep testing the rest
            failures.append(f"{name}: {type(error).__name__}: {error}")
            print(f"  \u2717 {name}: {type(error).__name__}: {error}")
            return False

    try:
        health = client.get(f"{bookarm}/takeout/health", timeout=10)
        if health.status_code != 200 or health.json().get("mode") != "fake":
            print("fake BookArm is not reachable through the web proxy; "
                  "run deploy/local/start-bookarm-fake.sh first")
            return 2

        def create_template():
            nonlocal template_id
            response = client.post(
                f"{bookarm}/studio/library",
                files={"image": ("spine.png", make_spine_image(), "image/png")},
                data={"source": "workflow-selftest", "name": "冒烟书脊"},
            )
            response.raise_for_status()
            payload = response.json()
            template_id = payload["id"]
            return f"{template_id} features={payload['selfCheck']['feature_count']}"

        def create_robot():
            nonlocal robot_created
            client.delete(f"{api}/robots/{ROBOT_ID}")
            response = client.post(
                f"{api}/robots",
                json={"id": ROBOT_ID, "name": "流程自检机器人", "gatewayHost": "127.0.0.1"},
            )
            response.raise_for_status()
            robot_created = True
            return response.json()["id"]

        def bring_online():
            telemetry = {
                "robotId": ROBOT_ID,
                "frameId": "map",
                "mapId": MAP_ID,
                "nav2Ready": True,
                "chassisReady": True,
                "x": 0.5,
                "y": 0.5,
                "yaw": 0.0,
                "localizationStatus": "localized",
                "localizationScanMode": "dual",
                "imuReady": True,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            publisher = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id=f"workflow-{uuid.uuid4().hex[:8]}"
            )
            publisher.connect(args.mqtt_host, args.mqtt_port, 30)
            publisher.loop_start()
            try:
                publisher.publish(f"fleet/{ROBOT_ID}/telemetry", json.dumps(telemetry), qos=0).wait_for_publish(
                    timeout=5
                )
            finally:
                publisher.loop_stop()
                publisher.disconnect()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                robots = client.get(f"{api}/robots", timeout=15).json()
                robot = next((item for item in robots if item["id"] == ROBOT_ID), None)
                if robot and robot["status"] == "idle":
                    return f"status={robot['status']} map={robot.get('mapId')}"
                time.sleep(0.5)
            raise TimeoutError("robot did not become idle after telemetry")

        def takeout():
            response = client.post(
                f"{api}/circulation/complete-takeout",
                json={
                    "robotId": ROBOT_ID,
                    "templateId": template_id,
                    "liftHeightMm": 230,
                    "destinationSlot": 2,
                    "sendNavigation": False,
                    "liftSpeedLevel": 1,
                },
            )
            response.raise_for_status()
            task = response.json()
            final = poll_task(client, api, task["id"], args.timeout)
            if final["status"] != "completed":
                raise RuntimeError(f"{final['status']}: {final.get('failureReason')}")
            return f"{final['id']} {final['workflowMessage']}"

        def midreturn():
            response = client.post(
                f"{api}/circulation/complete-return",
                json={
                    "robotId": ROBOT_ID,
                    "templateId": template_id,
                    "liftHeightMm": 230,
                    "sourceSlot": 2,
                    "sendNavigation": False,
                    "liftSpeedLevel": 1,
                    "returnMode": "mid",
                },
            )
            response.raise_for_status()
            task = response.json()
            final = poll_task(client, api, task["id"], args.timeout)
            if final["status"] != "completed":
                raise RuntimeError(f"{final['status']}: {final.get('failureReason')}")
            return f"{final['id']} {final['workflowMessage']}"

        print("fake BookArm workflow test")
        if not step("upload spine template via proxy", create_template):
            return 2
        if not step("register temporary robot", create_robot):
            return 2
        if not step("bring robot online via telemetry", bring_online):
            return 2
        step("complete takeout (fake arm)", takeout)
        step("complete mid-return (fake arm)", midreturn)
    finally:
        if template_id:
            try:
                client.delete(f"{bookarm}/studio/library/{template_id}")
            except Exception:  # noqa: BLE001
                pass
        if robot_created:
            try:
                client.delete(f"{api}/robots/{ROBOT_ID}")
            except Exception:  # noqa: BLE001
                pass

    if failures:
        print("\nFAILED:")
        for failure in failures:
            print("  " + failure)
        return 1
    print("\nworkflow completed (takeout + mid-return)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
