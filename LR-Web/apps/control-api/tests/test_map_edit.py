from base64 import b64encode

from fastapi.testclient import TestClient

from app.api import operations
from app.main import app
from app.map_files import PgmImage, edit_pgm_pixels, parse_pgm, pgm_binary
from app.schemas import MapImportRequest, User
from app.store import store


def test_edit_pgm_pixels_uses_bottom_origin_coordinates() -> None:
    image = PgmImage(width=2, height=2, max_value=255, pixels=bytes([0, 0, 205, 205]))

    edited = edit_pgm_pixels(image, [(0, 0, 100), (1, 1, 0)])

    assert edited.pixels == bytes([0, 254, 0, 205])
    assert parse_pgm(pgm_binary(edited)).pixels == edited.pixels


def test_saved_map_edit_creates_a_new_version_without_changing_source(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(store, "map_storage_dir", tmp_path)
    monkeypatch.setattr(operations, "register_imported_map", lambda *_args, **_kwargs: (True, None))
    source_id = "MAP-EDIT-SOURCE"
    source = None
    created = None
    user = User(username="tester", name="Tester", role="admin")
    yaml_data = b"image: map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n"
    pgm_data = b"P5\n2 2\n255\n" + bytes([0, 0, 205, 205])
    try:
        source = store.import_map(
            MapImportRequest(
                id=source_id,
                name="原始地图",
                yamlName="map.yaml",
                yamlContent=b64encode(yaml_data).decode("ascii"),
                pgmName="map.pgm",
                pgmContent=b64encode(pgm_data).decode("ascii"),
            ),
            user,
        )
        response = TestClient(app).post(
            f"/api/v1/library/maps/{source_id}/edit",
            json={"name": "编辑地图", "points": [{"x": 0, "y": 0, "value": 100}, {"x": 1, "y": 1, "value": 0}]},
        )
        assert response.status_code == 201
        created = response.json()
        assert created["id"] != source_id
        assert created["name"] == "编辑地图"
        assert created["vehicleRegistered"] is True
        assert (tmp_path / source_id / "map.pgm").read_bytes() == pgm_data
        assert (tmp_path / created["id"] / "map.pgm").read_bytes().endswith(bytes([0, 254, 0, 205]))
        assert (tmp_path / created["id"] / "preview.png").is_file()
    finally:
        for map_id in {created["id"] if created else None, source.id if source else source_id} - {None}:
            store.delete_map_version(map_id, user)
