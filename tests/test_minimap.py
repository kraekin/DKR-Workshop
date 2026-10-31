"""field protection, source projection and mixed asset round trips."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import hashlib
import json
import math
import struct
import numpy as np
import pytest

from src.core.editing import EditError, EditSession, n64_checksums
from src.core.materials import MaterialEdit, validate_material_edit
from src.core.minimap import (MINIMAP_FIELDS, MinimapSettings, copy_minimap, edit_minimap,
    minimap_mask, minimap_changes, project_markers, load_minimap_tiles, tile_bounds,
    validate_minimap_edit, validate_model_edit)
from src.core.rom import AssetType, RomImage, LUT_START, LUT_END, REV1_SHA1, parse_asset_lut


@pytest.fixture(scope="module")
def session() -> EditSession:
    return EditSession(RomImage.from_file(next(Path.cwd().glob("*.z64"))))


def test_noop_all_models_and_existing_sprite_references(session: EditSession) -> None:
    refs = session.minimap_references
    assert len(refs) == 189 and {162, 172, 175, 177}.isdisjoint(ref.sprite_id for ref in refs)
    for index in range(session.rom.count(AssetType.LEVEL_MODELS)):
        raw = session.track_model(index).raw_data
        settings = MinimapSettings.from_bytes(raw)
        assert edit_minimap(raw, settings.values, refs) == raw
        validate_model_edit(raw, raw, session.material_references, refs)
        sprite, tiles = load_minimap_tiles(session.rom, int(settings.values["sprite"]))
        assert tiles and sprite.sprite_id == settings.values["sprite"]
        assert all(tile.frame.pixels.shape[2] == 4 for tile in tiles)
    assert not session.dirty and session.build_rom() is session.rom.data


@pytest.mark.parametrize("key,value", [("sprite", 3), ("rotation", 65535), ("scale_x", -1.25),
    ("scale_y", 0.), ("adv1_x", -32768), ("adv1_y", 32767), ("adv2_x", -37),
    ("adv2_y", 23), ("red", 10), ("green", 20), ("blue", 30)])
def test_each_field_changes_only_its_exact_bytes(session: EditSession, key: str, value: int | float) -> None:
    original = session.track_model(5).raw_data
    raw = bytearray(original)
    raw[0x26:0x28] = b"\xAB\xCD"
    raw[0x38] = 0xA9
    raw = bytes(raw)
    updated = edit_minimap(raw, {key: value}, session.minimap_references)
    field = next(field for field in MINIMAP_FIELDS if field.key == key)
    changed = {i for i, (a, b) in enumerate(zip(raw, updated)) if a != b}
    assert changed and changed <= set(range(field.offset, field.offset + field.size))
    assert updated[0x26:0x28] == raw[0x26:0x28] and updated[0x38] == 0xA9
    assert MinimapSettings.from_bytes(updated).values[key] == value
    assert len(minimap_changes(raw, updated)) == 1


@pytest.mark.parametrize("changes", [{"sprite": -1}, {"sprite": 193}, {"sprite": 162},
    {"rotation": -1}, {"rotation": 65536}, {"rotation": 1.5}, {"scale_x": float("nan")},
    {"scale_y": float("inf")}, {"scale_x": 1e39}, {"adv1_x": -32769}, {"adv2_y": 32768},
    {"red": 256}, {"blue": True}, {"not_a_field": 1}])
def test_invalid_edits_are_atomic(session: EditSession, changes: dict[str, int | float]) -> None:
    s = EditSession(session.rom)
    raw = s.track_model(5).raw_data
    with pytest.raises(EditError):
        s.edit_minimap(5, {"adv1_x": 30, **changes})
    assert s.track_model(5).raw_data == raw and not s.dirty and not s.can_undo


def test_protected_fields_and_separate_writer_boundaries(session: EditSession) -> None:
    raw = session.track_model(5).raw_data
    for offset in (0, 0x18, 0x26, 0x27, 0x38, 0x3C, 0x47, 0x48, len(raw) - 1):
        updated = bytearray(raw); updated[offset] ^= 1
        with pytest.raises(ValueError):
            validate_minimap_edit(raw, bytes(updated), session.minimap_references)
        with pytest.raises(ValueError):
            validate_model_edit(raw, bytes(updated), session.material_references, session.minimap_references)
    updated = edit_minimap(raw, {"rotation": 90}, session.minimap_references)
    with pytest.raises(ValueError, match="protected"):
        validate_material_edit(raw, updated, session.material_references)
    for data in (b"", raw[:0x4B]):
        with pytest.raises(ValueError): MinimapSettings.from_bytes(data)
        with pytest.raises(ValueError): minimap_mask(len(data))
    with pytest.raises(ValueError): validate_model_edit(raw, raw + b"\0", session.material_references, session.minimap_references)
    for value in (float("nan"), float("inf")):
        bad = bytearray(raw); struct.pack_into(">f", bad, 0x28, value)
        with pytest.raises(ValueError, match="finite"):
            validate_model_edit(raw, bytes(bad), session.material_references, session.minimap_references)


def test_degenerate_bounds_projection_and_writer_rejection(session: EditSession) -> None:
    raw = bytearray(session.track_model(5).raw_data)
    struct.pack_into(">h", raw, 0x3E, struct.unpack_from(">h", raw, 0x3C)[0])
    with pytest.raises(ValueError, match="nonzero"):
        edit_minimap(bytes(raw), {"rotation": 180}, session.minimap_references)
    with pytest.raises(ValueError, match="nonzero"):
        project_markers(MinimapSettings.from_bytes(bytes(raw)), np.zeros((1, 2)), (0, 0))


def test_source_projection_degrees_scales_offsets_and_mirror(session: EditSession) -> None:
    settings = MinimapSettings.from_bytes(session.track_model(5).raw_data)
    values = dict(settings.values, rotation=0, scale_x=1., scale_y=1., adv1_x=0, adv1_y=0, adv2_x=10, adv2_y=-5)
    settings = replace(settings, values=values, bounds=(0, 100, 0, 1, 0, 200))
    points = np.array([[0, 0], [100, 200], [50, 100]])
    np.testing.assert_allclose(project_markers(settings, points, (8, 12)), [[-8, 12], [22, -48], [7, -18]])
    np.testing.assert_allclose(project_markers(settings, points, (8, 12), mirrored=True), [[2, 7], [-28, -53], [-13, -23]])
    rotated = replace(settings, values=dict(values, rotation=90))
    angle = (90 * 65535 // 360) * math.tau / 65536
    expected = [30 * math.cos(angle) - 60 * math.sin(angle) - 8,
                -(30 * math.sin(angle) + 60 * math.cos(angle)) + 12]
    np.testing.assert_allclose(project_markers(rotated, points[1:2], (8, 12))[0], expected)
    scaled = replace(settings, values=dict(values, scale_x=2., scale_y=-.5))
    np.testing.assert_allclose(project_markers(scaled, points[1:2], (8, 12)), [[52, 42]])
    assert project_markers(settings, np.empty((0, 2)), (8, 12)).shape == (0, 2)
    for bad in (np.zeros(3), np.ones((1, 3)), np.array([[np.inf, 0]])):
        with pytest.raises(ValueError): project_markers(settings, bad, (0, 0))
    sprite, tiles = load_minimap_tiles(session.rom, 1)
    for tile in tiles:
        a = tile_bounds(tile, sprite.anchor)
        b = tile_bounds(tile, sprite.anchor, mirrored=True)
        assert b == (-sprite.anchor[0] - a[2], a[1], -sprite.anchor[0] - a[0], a[3])


def test_material_and_minimap_history_and_independent_revert(session: EditSession) -> None:
    s = EditSession(session.rom)
    original = s.track_model(5).raw_data
    assert s.edit_minimap(5, {"rotation": 90, "adv2_x": -120, "blue": 100})
    minimap = s.track_model(5).raw_data
    assert s.edit_track_materials(5, (MaterialEdit("surface", (0,), 2),))
    combined = s.track_model(5).raw_data
    assert copy_minimap(original, combined) == minimap
    assert s.revert_minimap(5)
    materials = s.track_model(5).raw_data
    assert materials != original and copy_minimap(materials, minimap) == combined
    s.undo(); assert s.track_model(5).raw_data == combined
    s.undo(); assert s.track_model(5).raw_data == minimap
    s.redo(); assert s.track_model(5).raw_data == combined
    assert s.revert_track_materials(5) and s.track_model(5).raw_data == minimap
    s.undo(); assert s.track_model(5).raw_data == combined
    s.revert_minimap(5); s.revert_track_materials(5)
    assert s.build_rom() == s.rom.data and not s.dirty


def test_project_export_shared_dependencies_and_untouched_assets(session: EditSession, tmp_path: Path) -> None:
    s = EditSession(session.rom)
    s.edit_minimap(5, {"sprite": 3, "rotation": 180, "scale_x": 1.2, "adv1_y": -100, "adv2_y": 50, "green": 120})
    s.edit_track_materials(5, (MaterialEdit("surface", (0,), 2),))
    s.set_level_field(5, "laps", 2)
    project = s.save_project(tmp_path / "minimap.dkrproj", 5)
    assert json.loads(project.read_text())["version"] == 6
    loaded = EditSession.load_project(project)
    assert not loaded.dirty and loaded.track_model(5).raw_data == s.track_model(5).raw_data
    report = loaded.export_report()
    diff = next(item for item in report.assets if item.section == 27)
    assert any("Marker rotation" in row for row in diff.changes)
    assert any("Texture slot" in row for row in diff.changes)
    assert any("Ancient Lake" in row for row in diff.levels)
    output = loaded.build_rom()  # In memory only, no sample ROM.
    rebuilt = RomImage(output, "z64", parse_asset_lut(output, LUT_START, LUT_END))
    assert rebuilt.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True) == s.track_model(5).raw_data
    for section in range(50):
        if section not in (23, 26, 27): assert rebuilt.section(section) == session.rom.section(section)
    for index in range(55):
        if index != 5: assert rebuilt.read_asset(AssetType.LEVEL_MODELS, index) == session.rom.read_asset(AssetType.LEVEL_MODELS, index)
    assert len(output) == len(session.rom.data)
    assert struct.unpack_from(">II", output, 16) == n64_checksums(output)
    assert hashlib.sha1(session.rom.source_path.read_bytes()).hexdigest() == REV1_SHA1
    # No accepted tail means growth is refused before building an output.
    protected = bytearray(session.rom.data); protected[session.rom.sections[-1].end] = 1
    loaded.rom = RomImage(bytes(protected), "z64", session.rom.sections, session.rom.source_path)
    loaded._report_cache = None
    if loaded.export_report().growth_bytes > 0:
        assert not loaded.export_report().can_export
        with pytest.raises(EditError, match="padding"): loaded.build_rom()


def test_v4_material_projects_migrate_but_cannot_contain_minimap_overlays(session: EditSession, tmp_path: Path) -> None:
    s = EditSession(session.rom)
    s.edit_track_materials(5, (MaterialEdit("surface", (0,), 2),))
    doc = s.project_document(5); doc["version"] = 4
    path = tmp_path / "legacy.dkrproj"; path.write_text(json.dumps(doc))
    loaded = EditSession.load_project(path)
    assert loaded.track_model(5).raw_data == s.track_model(5).raw_data
    assert loaded.project_document()["version"] == 6
    doc["asset_edits"][0]["bytes"].append({"offset": 0x25, "value": 90})
    path.write_text(json.dumps(doc))
    with pytest.raises(EditError, match="protected"): EditSession.load_project(path)


@pytest.mark.parametrize("offset,value", [(0x26, 1), (0x38, 1), (0x3C, 1), (0x20, 255)])
def test_v5_project_rejects_protected_or_invalid_minimap_fields(session: EditSession, tmp_path: Path, offset: int, value: int) -> None:
    s = EditSession(session.rom)
    s.edit_minimap(5, {"rotation": 90})
    doc = s.project_document(5)
    doc["asset_edits"][0]["bytes"].append({"offset": offset, "value": value})
    path = tmp_path / "bad.dkrproj"; path.write_text(json.dumps(doc))
    with pytest.raises(EditError): EditSession.load_project(path)
