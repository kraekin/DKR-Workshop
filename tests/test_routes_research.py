"""Source-traced route writes and project-only research; no sample ROM files."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import json
import numpy as np
import pytest

from src.core.editing import EditSession, EditError
from src.core.objects import LevelObject, build_race_paths
from src.core.placement import patch_entry
from src.core.routes import lane_point, lane_entry, connection_entry, route_diagnostics, route_label
from src.core.research import FieldNote, compare_sessions, research_fields
from src.core.rom import RomImage, AssetType, parse_asset_lut, LUT_START, LUT_END
from src.renderer.camera import Camera, TranslationDrag, project_point


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


def changed(obj: LevelObject, **values: int | tuple[int, ...]) -> LevelObject:
    return replace(obj, raw_data=patch_entry(obj, parameters=values),
                   parameters=tuple(replace(p, value=values.get(p.name, p.value)) for p in obj.parameters))


def test_lane_world_projection_quantization_and_byte_isolation(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    obj = s.object((5, 48))
    assert lane_point(obj, 0) == (-1697.34375, 51, -7607)
    assert "Car/Hovercraft" in route_label(obj, (0, 0, 1))
    point = lane_point(obj, 0)
    raw = lane_entry(obj, 0, (point[0] + 29.6875, point[1] + 5.9375, point[2] + 100))
    assert {i for i, (a, b) in enumerate(zip(obj.raw_data, raw)) if a != b} == {0xB, 0xF}
    s.begin_group((obj.key,), "Move AI lane 0")
    s.preview_group({obj.key: raw})
    s.finish_group()
    assert s.object(obj.key).value("unkB") == -43 and s.object(obj.key).value("unkF") == 2
    assert s.undo() == obj.key and not s.dirty
    s.redo()
    loaded = EditSession.load_project(s.save_project(tmp_path / "lane.dkrproj", 5))
    assert loaded.object(obj.key).raw_data == raw
    data = loaded.build_rom()  # In-memory export only.
    rebuilt = RomImage(data, "z64", parse_asset_lut(data, LUT_START, LUT_END))
    original_sections = {i: rom.section(i) for i in range(50)}
    for i in range(50):
        if i not in (20, 21):
            assert rebuilt.section(i) == original_sections[i]
    yaw = changed(obj, angleY=16)
    p = lane_point(yaw, 0)
    assert p[0] == pytest.approx(obj.position[0])
    assert p[2] == pytest.approx(obj.position[2] + 157.34375)
    assert lane_entry(yaw, 0, p) == yaw.raw_data
    limits = lane_entry(obj, 1, (1e6, -1e6, obj.position[2]))
    assert limits[0xC] == 127 and limits[0x10] == 128
    with pytest.raises(ValueError): lane_entry(obj, 4, point)
    with pytest.raises(ValueError): lane_entry(obj, 0, (float("nan"), 0, 0))


def test_connection_slots_global_graph_and_atomic_rejections(rom: RomImage) -> None:
    s = EditSession(rom)
    a, b, c = (s.object((5, i)) for i in (31, 32, 33))
    other_map = replace(b, map_id=73, index=1)
    raw = connection_entry(a, 2, b.value("nodeID"), (a, other_map))
    assert [i for i, (x, y) in enumerate(zip(a.raw_data, raw)) if x != y] == [12]
    s.apply_entries({a.key: raw}, "Connect existing AI nodes")
    paths = build_race_paths((s.object(a.key), other_map), (0, 0, 1))
    assert len(paths) == 1 and paths[0].object_keys == (a.key, other_map.key)
    assert np.array_equal(paths[0].points, [a.position, b.position])
    assert s.undo() == a.key and not s.dirty
    for slot, target in ((4, 1), (0, 128), (0, -1), (0, 3), (0, a.value("nodeID"))):
        with pytest.raises(ValueError): connection_entry(a, slot, target, (a, b, c))
    linked = changed(a, adjacent=(1, 255, 255, 255))
    with pytest.raises(ValueError): connection_entry(linked, 1, 1, (a, b))
    with pytest.raises(ValueError): connection_entry(a, 0, 1, (a, b, other_map))
    assert not s.dirty
    assert connection_entry(linked, 0, 255, (linked, b)) == a.raw_data
    unusual = changed(a, adjacent=(127, 128, 254, 255))
    raw = connection_entry(unusual, 3, 1, (unusual, b))
    assert raw[10:13] == unusual.raw_data[10:13] and raw[13] == 1


def test_derived_lane_handles_keep_subunit_precision_beyond_origin_limits(rom: RomImage) -> None:
    obj = changed(replace(EditSession(rom).object((5, 48)), position=(32767, 0, 0)), scale=5, unkB=120)
    position = np.array(lane_point(obj, 0))
    assert position[0] > 32767
    camera = Camera()
    camera.set_view("Top")
    camera.target = position.copy()
    camera.position = camera.target - camera.forward * 100
    camera.ortho_height = 10
    matrix = camera.projection_matrix(1) @ camera.view_matrix()
    first = project_point(position, matrix, 800, 800)
    last = project_point(position + (5/32, 0, 0), matrix, 800, 800)
    drag = TranslationDrag.begin(position, None, *first, camera.forward, matrix, 800, 800)
    world = drag.world_at(*last)
    assert world[0] == pytest.approx(position[0] + 5/32, abs=1e-5)
    raw = lane_entry(obj, 0, world)
    assert raw[11] == 121 and raw[2:8] == obj.raw_data[2:8]
    with pytest.raises(ValueError): drag.world_at(*last, -1)


def test_graph_diagnostics_find_ambiguous_dangling_and_alternate_issues(rom: RomImage) -> None:
    s = EditSession(rom)
    a = changed(s.object((5, 31)), adjacent=(1, 1, 127, 0))
    b = s.object((5, 32))
    duplicate = replace(b, map_id=73)
    cp = s.object((5, 48))
    duplicate_cp = replace(cp, index=999)
    alt = changed(replace(cp, index=998), index=100, isAltCheckpoint=1)
    items = (a, b, duplicate, cp, duplicate_cp, alt)
    issues = route_diagnostics(items, (0, 0, 1))
    assert {"duplicate-node", "ambiguous-link", "dangling-link", "self-link", "duplicate-link",
            "duplicate-checkpoint", "orphan-alternate", "unmapped-set"} <= {i.code for i in issues}
    assert not build_race_paths((a, b, duplicate), (0, 0, 1))
    original = tuple(s.current_map(i).objects for i in (5, 73))
    stock = original[0] + original[1]
    assert {issue.code for issue in route_diagnostics(stock, (0, 0, 1))} <= {"checkpoint-order"}
    collision = (changed(cp, index=255), changed(replace(cp, index=997), index=0, isAltCheckpoint=1))
    assert "checkpoint-sort-collision" in {i.code for i in route_diagnostics(collision, (0, 0, 0))}
    too_many = tuple(replace(cp, index=i) for i in range(61))
    assert "checkpoint-capacity" in {i.code for i in route_diagnostics(too_many, (0, 0, 0))}


def test_field_metadata_covers_all_original_entry_schemas(rom: RomImage) -> None:
    s = EditSession(rom)
    count = 0
    for map_id in range(138):
        for obj in s.current_map(map_id).objects:
            fields = research_fields(obj)
            assert len({field.key for field in fields}) == len(fields)
            assert all(2 <= field.offset < field.offset + field.size <= obj.byte_size for field in fields)
            count += 1
    assert count == 9426


def test_research_history_never_changes_rom_and_notes_round_trip(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    key = (5, 48)
    signature = s._signature()
    assert s.set_note(key, "unk19", "Left → right confirmed in-game", "Observed change")
    assert s.dirty and s.undo_label == "Edit parameter note"
    assert s.build_rom() == rom.data and not s.export_report().assets
    assert s.undo() == key and not s.dirty and s._signature() == signature
    s.redo()
    s.set_experiment_name("HUD cue experiment")
    document = s.project_document(5)
    assert document["version"] == 6 and document["edits"] == []
    assert document["research"]["notes"][0]["field"] == "unk19"
    path = s.save_project(tmp_path / "notes.dkrproj", 5)
    loaded = EditSession.load_project(path)
    assert loaded.note(key, "unk19") == FieldNote("Left → right confirmed in-game", "Observed change")
    assert loaded.experiment_name == s.experiment_name and not loaded.dirty and not loaded.can_undo
    assert loaded.build_rom() == rom.data and not compare_sessions(s, loaded)
    s.set_parameter(key, "unk19", 4)
    s.set_note(key, "byte:24", "Still appears unused", "No visible change")
    before = s._signature(), loaded._signature()
    rows = compare_sessions(s, loaded)
    assert any(row[1] == "0x19 unk19" for row in rows)
    assert any(row[1] == "Note · byte:24" for row in rows)
    assert before == (s._signature(), loaded._signature())
    assert {f.status for f in research_fields(s.object(key))} >= {"Known", "Apparently unused", "Raw"}
    assert next(f for f in research_fields(changed(s.object(key), unk13=3)) if f.key == "unk13").status == "Unknown value"


@pytest.mark.parametrize("version", (1, 2, 3))
def test_old_projects_migrate_to_current_without_changing_bytes(rom: RomImage, tmp_path: Path, version: int) -> None:
    s = EditSession(rom)
    s.set_parameter((5, 48), "unk19", 4)
    doc = s.project_document(5)
    doc["version"] = version
    doc.pop("research")
    if version == 1:
        doc.pop("asset_edits")
    path = tmp_path / "legacy.dkrproj"
    path.write_text(json.dumps(doc))
    loaded = EditSession.load_project(path)
    assert loaded.project_document()["version"] == 6
    assert not compare_sessions(s, loaded) and not loaded.dirty


@pytest.mark.parametrize("bad", ("field", "hash", "duplicate", "result", "text", "experiment"))
def test_malformed_research_rejected(rom: RomImage, tmp_path: Path, bad: str) -> None:
    s = EditSession(rom)
    s.set_note((5, 48), "unk19", "Test", "Inconclusive")
    doc = s.project_document()
    note = doc["research"]["notes"][0]
    if bad == "field": note["field"] = "nonexistent"
    if bad == "hash": note["base_entry_sha1"] = "bad"
    if bad == "duplicate": doc["research"]["notes"].append(dict(note))
    if bad == "result": note["result"] = "Surely known"
    if bad == "text": note["text"] = ["not text"]
    if bad == "experiment": doc["research"]["experiment"] = 12
    path = tmp_path / "malformed.dkrproj"
    path.write_text(json.dumps(doc))
    with pytest.raises(EditError): EditSession.load_project(path)
