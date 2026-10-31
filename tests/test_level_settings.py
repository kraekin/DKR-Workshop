"""Source-verified level settings, isolated bytes, mixed history and ROM/project IO."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import pytest

from src.core.editing import EditError, EditSession, n64_checksums
from src.core.level_settings import FIELD_BY_KEY, LEVEL_FIELDS, SEQUENCE_NAMES, base_references, validate_header_edit
from src.core.rom import AssetType, LUT_START, LUT_END, REV1_SHA1, RomImage, parse_asset_lut


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


def test_all_headers_unchanged_and_reference_tables(rom: RomImage) -> None:
    session = EditSession(rom)
    assert len(SEQUENCE_NAMES) == 66
    references = session.level_references(5)
    assert references.ai_count == 10 and len(references.music) == 66
    assert references.music[10] == (10, "Ancient Lake")
    assert references.max_weather_density == 415
    assert references.skyboxes[0] == (-1, "None")
    assert dict(references.skyboxes)[209] == session.database.definitions[209].name
    assert dict(references.skyboxes)[209] != session.database.resolve(209).name
    for index in range(65):
        raw = rom.read_asset(AssetType.LEVEL_HEADERS, index)
        assert len(raw) == 0xC8
        validate_header_edit(raw, raw, session.level_references(index))
        for field in LEVEL_FIELDS:
            assert not session.set_level_field(index, field.key, field.read(raw))
    assert not session.dirty and not session.can_undo
    assert session.build_rom() == rom.data


@pytest.mark.parametrize("count", [0, -1, 257])
def test_malformed_music_reference_count_rejected(rom: RomImage, count: int) -> None:
    session = EditSession(rom)
    data = bytearray(rom.data)
    sequence_offset = struct.unpack_from(">I", data, rom.sections[38].start + 16)[0]
    struct.pack_into(">h", data, rom.sections[39].start + sequence_offset + 2, count)
    malformed = RomImage(bytes(data), "z64", rom.sections)
    with pytest.raises(ValueError, match="count"):
        base_references(malformed, session._catalog, session.database)


EXPERIMENTS = {
    "laps": 2, "vehicle": 1, "available_vehicles": 3,
    "ai_adv1": (0, 1, 2, 3, 4), "ai_adv2": (4, 3, 2, 1, 0),
    "fog_near": 100, "fog_far": 900, "fog_color": (12, 34, 56),
    "camera_fov": 55, "background_color": (10, 20, 30),
    "background_bottom": (40, 50, 60), "background_top": (70, 80, 90),
    "music": 9, "instruments": 0x1234, "weather_density": 8,
    "weather_type": 1, "weather_intensity": 128, "weather_opacity": 128,
    "weather_velocity": (-1, 2, -3),
}


@pytest.mark.parametrize("key,value", EXPERIMENTS.items())
def test_field_isolation_and_lossless_undo(rom: RomImage, key: str, value: object) -> None:
    session = EditSession(rom)
    original = rom.read_asset(AssetType.LEVEL_HEADERS, 5)
    field = FIELD_BY_KEY[key]
    session.set_level_field(5, key, value)
    edited = session.current_asset(AssetType.LEVEL_HEADERS, 5)
    assert field.read(edited) == value
    assert edited[:field.offset] == original[:field.offset]
    assert edited[field.offset + field.size:] == original[field.offset + field.size:]
    assert len(edited) == 0xC8 and edited[0xC4:] == original[0xC4:]
    session.undo()
    assert session.current_asset(AssetType.LEVEL_HEADERS, 5) == original and not session.dirty
    session.redo()
    assert session.current_asset(AssetType.LEVEL_HEADERS, 5) == edited


def test_skybox_and_checkpoint_references(rom: RomImage) -> None:
    session = EditSession(rom)
    references = session.level_references(5)
    current = session.level_header(5)
    replacement = next(i for i, _ in references.skyboxes if i != current.skybox_id)
    assert session.set_level_field(5, "skybox_id", replacement)
    assert session.level_header(5).skybox_id == replacement
    for vehicle, original in enumerate(current.checkpoint_sets):
        alternative = next((value for value in references.checkpoint_sets if value != original), None)
        if alternative is not None:
            sets = list(current.checkpoint_sets)
            sets[vehicle] = alternative
            assert session.set_level_field(5, "checkpoint_sets", tuple(sets))
            assert session.level_header(5).checkpoint_sets == tuple(sets)
            break
    else:
        pytest.fail("Expected at least two Ancient Lake checkpoint sets for this reference check")


@pytest.mark.parametrize("key,value", [
    ("laps", 0), ("laps", 4), ("laps", True), ("laps", 2.0),
    ("camera_fov", 0), ("camera_fov", 90), ("music", 66), ("music", -1),
    ("ai_adv1", (-1, 0, 0, 0, 0)), ("ai_adv1", (10, 0, 0, 0, 0)),
    ("ai_adv1", (1, 2)), ("checkpoint_sets", (99, 0, 0)),
    ("skybox_id", 1), ("weather_density", 416), ("weather_type", -1),
    ("weather_type", 2), ("weather_opacity", 256), ("weather_velocity", (0, 32768, 0)),
    ("fog_color", (0, 256, 0)), ("fog_far", 1024), ("instruments", 65536),
    ("world", 1), ("geometry_id", 2), ("race_type", 0),
])
def test_invalid_settings_are_atomic(rom: RomImage, key: str, value: object) -> None:
    session = EditSession(rom)
    with pytest.raises(EditError):
        session.set_level_field(5, key, value)
    assert not session.dirty and not session.can_undo and not session.modified_maps


def test_default_vehicle_must_be_allowed(rom: RomImage) -> None:
    session = EditSession(rom)
    session.set_level_field(5, "available_vehicles", 1)
    with pytest.raises(EditError, match="include"):
        session.set_level_field(5, "vehicle", 2)
    session.set_level_field(5, "available_vehicles", 5)
    session.set_level_field(5, "vehicle", 2)
    session.set_level_field(5, "available_vehicles", 4)
    assert session.level_header(5).vehicle == 2


@pytest.mark.parametrize("offset", [0, 1, 8, 0x34, 0x36, 0x49, 0x4C, 0x56, 0x74, 0xA4, 0xBA, 0xC4, 0xC7])
def test_project_cannot_patch_protected_header_bytes(rom: RomImage, tmp_path: Path, offset: int) -> None:
    session = EditSession(rom)
    session.set_level_field(5, "laps", 2)
    document = session.project_document()
    edit, = document["asset_edits"]
    base = rom.read_asset(AssetType.LEVEL_HEADERS, 5)
    edit["bytes"].append({"offset": offset, "value": base[offset] ^ 1})
    path = tmp_path / "protected.dkrproj"
    path.write_text(json.dumps(document))
    with pytest.raises(EditError, match="Protected"):
        EditSession.load_project(path)


@pytest.mark.parametrize("variant", ["hash", "duplicate", "offset", "value", "bytes", "index", "legacy"])
def test_malformed_asset_overlays_rejected(rom: RomImage, tmp_path: Path, variant: str) -> None:
    session = EditSession(rom)
    session.set_level_field(5, "laps", 2)
    document = session.project_document()
    edit = document["asset_edits"][0]
    if variant == "hash": edit["base_asset_sha1"] = "bad"
    elif variant == "duplicate": document["asset_edits"].append(edit.copy())
    elif variant == "offset": edit["bytes"].append(edit["bytes"][0].copy())
    elif variant == "value": edit["bytes"][0]["value"] = 256
    elif variant == "bytes": edit["bytes"] = None
    elif variant == "index": edit["index"] = 65
    elif variant == "legacy": document["version"] = 1
    path = tmp_path / "invalid.dkrproj"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        EditSession.load_project(path)


def test_mixed_header_object_history_project_and_relocated_rom(rom: RomImage, tmp_path: Path) -> None:
    session = EditSession(rom)
    obj = session.object((95, 0))
    session.set_position(obj.key, (obj.position[0] + 1, *obj.position[1:]))
    session.set_level_field(5, "laps", 2)
    session.set_level_field(0, "music", 9)
    session.undo()
    assert session.last_asset_key == (AssetType.LEVEL_HEADERS, 0)
    session.undo()
    assert session.level_header(5).laps == 3
    session.undo()
    assert session.last_asset_key is None and not session.dirty
    session.redo(); session.redo(); session.redo()
    path = session.save_project(tmp_path / "mixed.dkrproj", 5)
    loaded = EditSession.load_project(path)
    assert loaded.project_document(5) == session.project_document(5) and not loaded.dirty
    rebuilt = loaded.build_rom()
    assert len(rebuilt) == len(rom.data)
    assert n64_checksums(rebuilt) == struct.unpack_from(">2I", rebuilt, 0x10)
    parsed = RomImage(rebuilt, "z64", parse_asset_lut(rebuilt, LUT_START, LUT_END))
    assert parsed.read_asset(AssetType.LEVEL_HEADERS, 5)[0x4B] == 2
    assert parsed.read_asset(AssetType.LEVEL_HEADERS, 0)[0x52] == 9
    for i in range(50):
        if i not in (20, 21, 23):
            assert parsed.section(i) == rom.section(i)
    assert parsed.section(22) == rom.section(22)
    for i in range(65):
        assert parsed.read_asset(AssetType.LEVEL_HEADERS, i) == loaded.current_asset(AssetType.LEVEL_HEADERS, i)
    report = loaded.export_report()
    assert len(report.assets) == 3 and report.growth_bytes == 16
    assert "Laps: 3 → 2" in report.to_text()
    loaded.revert_level(5)
    assert loaded.dirty and loaded.level_header(5).laps == 3
    loaded.undo()
    assert not loaded.dirty and loaded.level_header(5).laps == 2
    assert hashlib.sha1(rom.source_path.read_bytes()).hexdigest() == REV1_SHA1


def test_header_only_export_preserves_every_other_section(rom: RomImage) -> None:
    session = EditSession(rom)
    session.set_level_field(5, "laps", 2)
    session.set_level_field(5, "music", 9)
    rebuilt = session.build_rom()
    parsed = RomImage(rebuilt, "z64", parse_asset_lut(rebuilt, LUT_START, LUT_END))
    assert parsed.sections == rom.sections
    for index in range(50):
        if index != 23:
            assert parsed.section(index) == rom.section(index)
    assert not session.modified_maps
    assert session.export_report().growth_bytes == 0
    assert len(session.export_report().assets) == 1
