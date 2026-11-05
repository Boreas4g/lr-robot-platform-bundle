"""Shelf-internal take/return orchestration with straight X-only base moves."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import Book, RobotPose

client = TestClient(app)


class FakeBookarmClient:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object] | str | float]] = []
        self.takeouts: list[dict[str, object]] = []
        self.midreturns: list[dict[str, object]] = []
        self.returns: list[dict[str, object]] = []
        self.measured_height_mm = 10.0
        self._takeout_count = 0
        self._midreturn_count = 0
        self._return_count = 0

    def create_takeout_task(self, **kwargs):  # noqa: ANN003, ANN201 - test double
        self._takeout_count += 1
        self.takeouts.append(kwargs)
        self.events.append(("takeout", kwargs))
        return {"id": f"BT-SHELF-TAKE-{self._takeout_count}", "state": "running"}

    def get_takeout_task(self, task_id):  # noqa: ANN001, ANN202 - test double
        return {"id": task_id, "state": "succeeded"}

    def cancel_takeout_task(self, task_id):  # noqa: ANN001, ANN202 - test double
        return {"id": task_id, "state": "cancelled"}

    def create_midreturn_task(self, **kwargs):  # noqa: ANN003, ANN201 - test double
        self._midreturn_count += 1
        self.midreturns.append(kwargs)
        self.events.append(("midreturn", kwargs))
        return {"id": f"BT-SHELF-MID-{self._midreturn_count}", "state": "running"}

    def get_midreturn_task(self, task_id):  # noqa: ANN001, ANN202 - test double
        return {"id": task_id, "state": "succeeded"}

    def cancel_midreturn_task(self, task_id):  # noqa: ANN001, ANN202 - test double
        return {"id": task_id, "state": "cancelled"}

    def create_return_task(self, **kwargs):  # noqa: ANN003, ANN201 - test double
        self._return_count += 1
        self.returns.append(kwargs)
        self.events.append(("return", kwargs))
        return {"id": f"BT-SHELF-END-{self._return_count}", "state": "running"}

    def get_return_task(self, task_id):  # noqa: ANN001, ANN202 - test double
        return {"id": task_id, "state": "succeeded"}

    def cancel_return_task(self, task_id):  # noqa: ANN001, ANN202 - test double
        return {"id": task_id, "state": "cancelled"}

    def move_lift(self, height_mm, speed_level=2):  # noqa: ANN001, ANN202 - test double
        self.events.append(("lift", height_mm))
        return {
            "target_height_mm": height_mm,
            "measured_height_mm": self.measured_height_mm,
        }


def _headers() -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "123456"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "robotId": "LR-01",
        "bookId": "BOOK-SHELF-1",
        "book2Id": "BOOK-SHELF-4",
        "referenceBook1Id": "BOOK-SHELF-2",
        "referenceBook2Id": "BOOK-SHELF-3",
        "shelf1Target": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "shelf2Target": {"x": 1.5, "y": 0.0, "yaw": 0.0},
        "shelf1AnnotationId": "ANN-SHELF-1",
        "shelf2AnnotationId": "ANN-SHELF-2",
        "mapId": "MAP-SHELF",
        "book1LiftHeightMm": 610,
        "book2LiftHeightMm": 620,
        "referenceBook1LiftHeightMm": 630,
        "referenceBook2LiftHeightMm": 640,
        "moveSpeedMps": 0.08,
        "enableVehicleAlignment": False,
        "bookStandSlot": 2,
        "book1TakeoutMode": "mid",
        "book2TakeoutMode": "standard",
        "book1ReturnMode": "end",
        "book2ReturnMode": "mid",
        "liftSpeedLevel": 2,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def shelf_context():
    from app.store import store

    robot_index = next(index for index, item in enumerate(store.robots) if item.id == "LR-01")
    original_robot = store.robots[robot_index]
    original_factory = store.bookarm_client_factory
    original_poll = store.takeout_poll_interval_s
    original_timeout = store.takeout_nav_timeout_s
    fake = FakeBookarmClient()
    store.bookarm_client_factory = lambda: fake
    store.takeout_poll_interval_s = 0.01
    store.takeout_nav_timeout_s = 2.0
    store.robots[robot_index] = original_robot.model_copy(
        update={
            "status": "idle",
            "mapId": "MAP-SHELF",
            "localizationStatus": "localized",
            "pose": RobotPose(
                frameId="map", x=0.0, y=0.0, yaw=0.0, capturedAt=datetime.now(UTC)
            ),
        }
    )
    book_ids = [f"BOOK-SHELF-{index}" for index in range(1, 9)]
    original_books = {book_id: store.books.get(book_id) for book_id in book_ids}
    for index, book_id in enumerate(book_ids, start=1):
        store.books[book_id] = Book(
            id=book_id,
            name=f"架内测试书{index}",
            templateId=f"TPL-SHELF-{index}",
            heightMm=500 + index * 100,
            createdAt="2026-01-01T00:00:00+00:00",
            updatedAt="2026-01-01T00:00:00+00:00",
        )
    before_task_ids = {task.id for task in store.tasks}
    yield store, fake, before_task_ids
    for task in store.tasks:
        if task.id not in before_task_ids and task.type == "shelf_internal":
            event = store._shelf_internal_cancels.get(task.id)
            if event is not None:
                event.set()
    store.bookarm_client_factory = original_factory
    store.takeout_poll_interval_s = original_poll
    store.takeout_nav_timeout_s = original_timeout
    current_index = next(index for index, item in enumerate(store.robots) if item.id == "LR-01")
    store.robots[current_index] = original_robot
    for book_id, original in original_books.items():
        if original is None:
            store.books.pop(book_id, None)
        else:
            store.books[book_id] = original


def _wait_parent(store, task_id: str, statuses: set[str], timeout_s: float = 5.0):  # noqa: ANN001, ANN202
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        task = next((item for item in store.tasks if item.id == task_id), None)
        if task is not None and task.status in statuses:
            return task
        time.sleep(0.01)
    raise AssertionError(f"shelf task {task_id} did not reach {statuses}")


def _wait_new_shelf_moves(store, before_task_ids: set[str], count: int):  # noqa: ANN001, ANN202
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        stages = [
            task
            for task in store.tasks
            if task.id not in before_task_ids and task.type == "shelf_move"
        ]
        if len(stages) >= count:
            return stages
        time.sleep(0.01)
    raise AssertionError(f"expected {count} shelf_move stages")


def _complete_shelf_move(store, stage, fake: FakeBookarmClient, label: str) -> None:  # noqa: ANN001
    command_id = stage.id.replace("TSK-", "CMD-", 1)
    store.handle_gateway_event(
        {"event": "shelf_move_dispatching", "robotId": "LR-01", "commandId": command_id}
    )
    fake.events.append(("shelf_move", label))
    store.handle_gateway_event(
        {"event": "command_completed", "robotId": "LR-01", "commandId": command_id}
    )


def test_shelf_internal_runs_four_arm_actions_and_two_low_lift_x_moves(shelf_context) -> None:  # noqa: ANN001
    store, fake, before_task_ids = shelf_context
    created = client.post(
        "/api/v1/circulation/shelf-internal", headers=_headers(), json=_payload()
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    first_stage = _wait_new_shelf_moves(store, before_task_ids, 1)[0]
    assert len(fake.takeouts) == 1
    assert fake.returns == []
    assert fake.midreturns == []
    _complete_shelf_move(store, first_stage, fake, "书架2")

    stages = _wait_new_shelf_moves(store, before_task_ids, 2)
    second_stage = next(item for item in stages if item.id != first_stage.id)
    assert len(fake.takeouts) == 2
    assert len(fake.returns) == 1
    assert fake.midreturns == []
    _complete_shelf_move(store, second_stage, fake, "书架1")

    completed = _wait_parent(store, task_id, {"completed"})
    assert completed.progress == 100
    assert [event[0] for event in fake.events] == [
        "takeout",
        "lift",
        "shelf_move",
        "return",
        "takeout",
        "lift",
        "shelf_move",
        "midreturn",
    ]
    assert [item["book_id"] for item in fake.takeouts] == [
        "BOOK-SHELF-1",
        "BOOK-SHELF-4",
    ]
    assert [item["takeout_mode"] for item in fake.takeouts] == ["mid", "standard"]
    assert [item["template_id"] for item in fake.takeouts] == [
        "TPL-SHELF-1",
        "TPL-SHELF-4",
    ]
    assert [event[1] for event in fake.events if event[0] == "lift"] == [10.0, 10.0]
    assert all(item["enable_vehicle_alignment"] is False for item in fake.takeouts)
    assert fake.returns[0]["book_id"] == "BOOK-SHELF-1"
    assert fake.returns[0]["template_id"] == "TPL-SHELF-3"
    assert fake.returns[0]["target_height_mm"] == 640
    assert fake.returns[0]["enable_vehicle_alignment"] is False
    assert fake.midreturns[0]["book_id"] == "BOOK-SHELF-4"
    assert fake.midreturns[0]["template_id"] == "TPL-SHELF-2"
    assert fake.midreturns[0]["target_height_mm"] == 630
    assert fake.midreturns[0]["enable_vehicle_alignment"] is False
    assert [item["destination_slot"] for item in fake.takeouts] == [2, 2]
    assert fake.returns[0]["source_slot"] == 2
    assert fake.midreturns[0]["source_slot"] == 2
    assert [item["target_height_mm"] for item in fake.takeouts] == [610, 620]
    assert completed.workflowDetails["book2Id"] == "BOOK-SHELF-4"
    assert completed.workflowDetails["book1LiftHeightMm"] == 610
    assert completed.workflowDetails["book2LiftHeightMm"] == 620
    assert completed.workflowDetails["referenceBook1LiftHeightMm"] == 630
    assert completed.workflowDetails["referenceBook2LiftHeightMm"] == 640
    assert completed.workflowDetails["book1TakeoutMode"] == "mid"
    assert completed.workflowDetails["book2TakeoutMode"] == "standard"
    assert completed.workflowDetails["book1ReturnMode"] == "end"
    assert completed.workflowDetails["book2ReturnMode"] == "mid"
    assert completed.workflowDetails["moveSpeedMps"] == 0.08
    assert completed.workflowDetails["enableVehicleAlignment"] is False

    commands = [
        command
        for command in store.commands.values()
        if command.command == "shelf_move" and command.commandId.replace("CMD-", "TSK-", 1) not in before_task_ids
    ]
    assert len(commands) == 2
    assert commands[0].payload["x"] == 1.5
    assert commands[1].payload["x"] == 0.0
    assert all(command.payload["speedMps"] == 0.08 for command in commands)
    assert all(command.payload["controlMode"] == "differential" for command in commands)


def test_loop_mode_appends_two_more_take_return_rounds(shelf_context) -> None:  # noqa: ANN001
    store, fake, before_task_ids = shelf_context
    created = client.post(
        "/api/v1/circulation/shelf-internal",
        headers=_headers(),
        json=_payload(
            enableLoopMode=True,
            book3Id="BOOK-SHELF-5",
            book4Id="BOOK-SHELF-8",
            referenceBook3Id="BOOK-SHELF-6",
            referenceBook4Id="BOOK-SHELF-7",
            book3LiftHeightMm=650,
            book4LiftHeightMm=660,
            referenceBook3LiftHeightMm=670,
            referenceBook4LiftHeightMm=680,
            book3TakeoutMode="standard",
            book4TakeoutMode="mid",
            book3ReturnMode="end",
            book4ReturnMode="mid",
        ),
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    completed_stages = set()
    for label in ("书架2", "书架1", "书架2", "书架1"):
        count = len(completed_stages) + 1
        stages = _wait_new_shelf_moves(store, before_task_ids, count)
        stage = next(item for item in stages if item.id not in completed_stages)
        completed_stages.add(stage.id)
        _complete_shelf_move(store, stage, fake, label)

    completed = _wait_parent(store, task_id, {"completed"})
    assert [event[0] for event in fake.events] == [
        "takeout", "lift", "shelf_move", "return",
        "takeout", "lift", "shelf_move", "midreturn",
        "takeout", "lift", "shelf_move", "return",
        "takeout", "lift", "shelf_move", "midreturn",
    ]
    assert [item["book_id"] for item in fake.takeouts] == [
        "BOOK-SHELF-1", "BOOK-SHELF-4", "BOOK-SHELF-5", "BOOK-SHELF-8",
    ]
    assert [item["takeout_mode"] for item in fake.takeouts] == [
        "mid", "standard", "standard", "mid",
    ]
    assert [item["target_height_mm"] for item in fake.takeouts] == [610, 620, 650, 660]
    assert [item["book_id"] for item in fake.returns] == ["BOOK-SHELF-1", "BOOK-SHELF-5"]
    assert [item["template_id"] for item in fake.returns] == ["TPL-SHELF-3", "TPL-SHELF-7"]
    assert [item["target_height_mm"] for item in fake.returns] == [640, 680]
    assert [item["book_id"] for item in fake.midreturns] == ["BOOK-SHELF-4", "BOOK-SHELF-8"]
    assert [item["template_id"] for item in fake.midreturns] == ["TPL-SHELF-2", "TPL-SHELF-6"]
    assert [item["target_height_mm"] for item in fake.midreturns] == [630, 670]
    assert [event[1] for event in fake.events if event[0] == "lift"] == [10.0] * 4
    assert completed.workflowDetails["enableLoopMode"] is True
    assert completed.workflowDetails["book3Id"] == "BOOK-SHELF-5"
    assert completed.workflowDetails["book4Id"] == "BOOK-SHELF-8"
    assert completed.workflowDetails["referenceBook3Id"] == "BOOK-SHELF-6"
    assert completed.workflowDetails["referenceBook4Id"] == "BOOK-SHELF-7"

    commands = [
        command
        for command in store.commands.values()
        if command.command == "shelf_move"
        and command.commandId.replace("CMD-", "TSK-", 1) not in before_task_ids
    ]
    assert len(commands) == 4
    assert [command.payload["x"] for command in commands] == [1.5, 0.0, 1.5, 0.0]


def test_loop_mode_requires_the_additional_four_books(shelf_context) -> None:  # noqa: ANN001
    created = client.post(
        "/api/v1/circulation/shelf-internal",
        headers=_headers(),
        json=_payload(enableLoopMode=True),
    )
    assert created.status_code == 422


def test_shelf_internal_blocks_base_move_when_lift_is_not_at_minimum(shelf_context) -> None:  # noqa: ANN001
    store, fake, before_task_ids = shelf_context
    fake.measured_height_mm = 100.0
    created = client.post(
        "/api/v1/circulation/shelf-internal", headers=_headers(), json=_payload()
    )
    assert created.status_code == 201

    failed = _wait_parent(store, created.json()["id"], {"failed"})
    assert "禁止架内移动" in (failed.failureReason or "")
    assert len(fake.takeouts) == 1
    assert fake.midreturns == []
    assert not [
        task
        for task in store.tasks
        if task.id not in before_task_ids and task.type == "shelf_move"
    ]


def test_cancel_after_lowering_never_dispatches_a_base_move(shelf_context) -> None:  # noqa: ANN001
    store, fake, before_task_ids = shelf_context
    original_move_lift = fake.move_lift

    def move_lift_and_cancel(height_mm, speed_level=2):  # noqa: ANN001, ANN202
        result = original_move_lift(height_mm, speed_level=speed_level)
        for event in list(store._shelf_internal_cancels.values()):
            event.set()
        return result

    fake.move_lift = move_lift_and_cancel
    created = client.post(
        "/api/v1/circulation/shelf-internal", headers=_headers(), json=_payload()
    )
    assert created.status_code == 201

    _wait_parent(store, created.json()["id"], {"cancelled"})
    assert not [
        task
        for task in store.tasks
        if task.id not in before_task_ids and task.type == "shelf_move"
    ]


def test_navigation_only_repeats_two_points_without_book_actions(shelf_context) -> None:  # noqa: ANN001
    store, fake, before_task_ids = shelf_context
    payload = _payload(navigationOnly=True)
    for key in ("bookId", "book2Id", "referenceBook1Id", "referenceBook2Id"):
        payload.pop(key)
    created = client.post(
        "/api/v1/circulation/shelf-internal", headers=_headers(), json=payload
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    first_stage = _wait_new_shelf_moves(store, before_task_ids, 1)[0]
    _complete_shelf_move(store, first_stage, fake, "书架2")
    stages = _wait_new_shelf_moves(store, before_task_ids, 2)
    second_stage = next(item for item in stages if item.id != first_stage.id)
    _complete_shelf_move(store, second_stage, fake, "书架1")
    third_stage = next(
        item
        for item in _wait_new_shelf_moves(store, before_task_ids, 3)
        if item.id not in {first_stage.id, second_stage.id}
    )

    assert fake.takeouts == []
    assert fake.returns == []
    assert fake.midreturns == []
    assert [event[0] for event in fake.events] == [
        "lift",
        "shelf_move",
        "lift",
        "shelf_move",
        "lift",
    ]
    assert created.json()["workflowDetails"]["navigationOnly"] is True
    assert third_stage.annotationId == "ANN-SHELF-2"
    parent = _wait_parent(store, task_id, {"running"})
    assert parent.workflowDetails["navigationCycles"] == 1
    commands = [
        command
        for command in store.commands.values()
        if command.command == "shelf_move"
        and command.commandId.replace("CMD-", "TSK-", 1) not in before_task_ids
    ]
    assert len(commands) == 3
    assert all(command.payload["xToleranceM"] == 0.02 for command in commands)
    cancelled = client.post(
        f"/api/v1/circulation/shelf-internal/{task_id}/cancel", headers=_headers()
    )
    assert cancelled.status_code == 202
    _wait_parent(store, task_id, {"cancelled"})


def test_navigation_only_cancel_during_dwell_skips_return_move(shelf_context) -> None:  # noqa: ANN001
    store, fake, before_task_ids = shelf_context
    created = client.post(
        "/api/v1/circulation/shelf-internal",
        headers=_headers(),
        json=_payload(navigationOnly=True),
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    first_stage = _wait_new_shelf_moves(store, before_task_ids, 1)[0]
    _complete_shelf_move(store, first_stage, fake, "书架2")

    cancelled = client.post(
        f"/api/v1/circulation/shelf-internal/{task_id}/cancel", headers=_headers()
    )
    assert cancelled.status_code == 202
    _wait_parent(store, task_id, {"cancelled"})
    assert len([event for event in fake.events if event[0] == "shelf_move"]) == 1
    assert fake.takeouts == []
    assert fake.returns == []
    assert fake.midreturns == []


def test_shelf_internal_rejects_duplicate_reference_books(shelf_context) -> None:  # noqa: ANN001
    created = client.post(
        "/api/v1/circulation/shelf-internal",
        headers=_headers(),
        json=_payload(referenceBook2Id="BOOK-SHELF-1"),
    )
    assert created.status_code == 422


def test_shelf_internal_rejects_the_same_target_book_for_both_rounds(shelf_context) -> None:  # noqa: ANN001
    created = client.post(
        "/api/v1/circulation/shelf-internal",
        headers=_headers(),
        json=_payload(book2Id="BOOK-SHELF-1"),
    )
    assert created.status_code == 422


def test_lift_move_waits_for_the_drivers_position_feedback(monkeypatch) -> None:  # noqa: ANN001
    from app.bookarm_client import BookarmClient

    class FakeConnection:
        def __init__(self) -> None:
            self.timeout_s = None
            self.responses = [
                b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n'
                b'{"target_height_mm": 10.0, "measured_height_mm": 10.0}',
                b"",
            ]

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *_args):  # noqa: ANN002, ANN204
            return None

        def settimeout(self, timeout_s) -> None:  # noqa: ANN001
            self.timeout_s = timeout_s

        def connect(self, socket_path) -> None:  # noqa: ANN001
            assert socket_path == "/run/test-bookarm.sock"

        def sendall(self, payload) -> None:  # noqa: ANN001
            assert b'"height_mm": 10.0' in payload

        def recv(self, _size):  # noqa: ANN002, ANN201
            return self.responses.pop(0)

    connection = FakeConnection()
    monkeypatch.setattr("app.bookarm_client.socket.socket", lambda *_args: connection)
    client = BookarmClient("/run/test-bookarm.sock", timeout_s=10.0)

    result = client.move_lift(10.0)

    assert result["measured_height_mm"] == 10.0
    assert connection.timeout_s == 55.0
