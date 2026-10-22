"""Runtime factories must connect each workflow to the vehicle alignment service."""

from pathlib import Path

from bookarm.api.requests import ReturnBookStage, TakeBookStage
from bookarm.devices.camera.service import D435BookSpineLocatorConfig
from bookarm.infrastructure import factory
from bookarm.service import composition


def _stub_devices(monkeypatch, module):
    monkeypatch.setattr(module, "ArmService", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module, "D435BookSpineLocator", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module, "AimLiftService", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module, "RodMotorService", lambda *_args, **_kwargs: object())


def test_direct_factories_inject_vehicle_alignment_client(monkeypatch):
    align_client = object()
    monkeypatch.setattr(factory, "VehicleAlignClient", lambda: align_client)
    _stub_devices(monkeypatch, factory)

    take_runtime = factory.create_bookarm_runtime(
        book_stand_slots_path=Path("unused-slots.json"),
        camera_calibration_path=Path("unused-calibration.json"),
        take_book_stop_after_stage=TakeBookStage.POST_VISION_ALIGN,
    )
    assert take_runtime.sdk._take_book.vehicle_align is align_client
    assert take_runtime.sdk._return_book.vehicle_align is align_client

    return_runtime = factory.create_return_book_runtime(
        book_stand_pickup_slots_path=Path("unused-pickup-slots.json"),
        camera_calibration_path=Path("unused-calibration.json"),
        stop_after_stage=ReturnBookStage.POST_VISION_ALIGN,
    )
    assert return_runtime.sdk._take_book.vehicle_align is align_client
    assert return_runtime.sdk._return_book.vehicle_align is align_client


def test_combined_runtime_injects_one_alignment_client_into_all_workflows(monkeypatch):
    align_client = object()
    monkeypatch.setattr(composition, "VehicleAlignClient", lambda: align_client)
    monkeypatch.setattr(composition, "_load_camera_config", D435BookSpineLocatorConfig)
    monkeypatch.setattr(composition, "load_book_stand_slots", lambda _path: {})
    monkeypatch.setattr(composition, "load_book_stand_pickup_slots", lambda _path: {})
    _stub_devices(monkeypatch, composition)

    combined = composition.create_combined_runtime(
        book_stand_slots_path=Path("unused-take-slots.json"),
        book_stand_pickup_slots_path=Path("unused-pickup-slots.json"),
        camera_calibration_path=Path("unused-calibration.json"),
    )

    sdk = combined.runtime.sdk
    assert combined.vehicle is align_client
    assert sdk._take_book.vehicle_align is align_client
    assert sdk._mid_return.vehicle_align is align_client
    assert sdk._return_book.vehicle_align is align_client
