"""Byte-preserving experiments, edit history, projects and rebuilt ROM assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import pytest

from src.core.editing import EditError, EditSession, n64_checksums
from src.core.objects import load_object_database
from src.core.rom import AssetError, AssetType, LUT_END, LUT_START, REV1_SHA1, RomImage, parse_asset_lut

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def rom() -> RomImage:
    paths = list(ROOT.glob("*.z64"))
    if not paths:
        pytest.skip("Local USA Rev 1 ROM not present")
    return RomImage.from_file(paths[0])


@pytest.fixture
def session(rom: RomImage) -> EditSession:
    return EditSession(rom)


def test_original_checksum_and_no_edit_export_identity(session: EditSession, rom: RomImage) -> None:
    assert n64_checksums(rom.data) == struct.unpack_from(">2I", rom.data, 0x10)
    assert session.build_rom() == rom.data
    assert not session.dirty and not session.can_undo and not session.can_redo
    assert session.undo() is None and session.redo() is None


def test_position_property_raw_edit_and_undo_redo_are_lossless(session: EditSession) -> None:
    obj = next(o for o in session.current_map(5).objects if o.definition.behavior_id == 2)
    key = obj.key
    assert session.set_position(key, (-32768, 32767, 123))
    assert session.object(key).position == (-32768, 32767, 123)
    assert session.object(key).raw_data[:2] == obj.raw_data[:2]
    assert session.object(key).raw_data[8:] == obj.raw_data[8:]
    assert session.set_parameter(key, "radius", 80)
    assert session.object(key).value("radius") == 80
    assert session.set_raw_byte(key, 9, 255)
    assert session.object(key).value("radius") == 255
    assert session.dirty and session.modified_maps == (5,)
    session.undo()
    assert session.object(key).value("radius") == 80
    session.undo(); session.undo()
    assert session.object(key) == obj and not session.dirty and not session.modified_maps
    session.redo(); session.redo(); session.redo()
    assert session.object(key).value("radius") == 255
    assert session.revert_object(key)
    assert session.object(key) == obj and not session.modified_maps
    session.undo()
    assert session.object(key).value("radius") == 255


def test_nop_keeps_history_and_new_edit_discards_redo(session: EditSession) -> None:
    obj = session.current_map(5).objects[0]
    assert not session.set_position(obj.key, obj.position)
    assert not session.can_undo
    session.set_position(obj.key, (100, 200, 300))
    session.undo()
    assert session.can_redo
    assert not session.set_position(obj.key, obj.position)
    assert session.can_redo
    session.set_position(obj.key, (300, 200, 100))
    assert not session.can_redo


@pytest.mark.parametrize("kind,value", [("position", (-32769, 0, 0)), ("position", (0, 32768, 0)),
                                        ("position", (0, 1.5, 0)), ("position", (0, True, 0)),
                                        ("byte", -1), ("byte", 256), ("byte", True), ("parameter", 256)])
def test_out_of_range_edits_are_atomic(session: EditSession, kind: str, value: object) -> None:
    obj = next(o for o in session.current_map(5).objects if o.definition.behavior_id == 2)
    with pytest.raises(EditError):
        if kind == "position":
            session.set_position(obj.key, value)
        elif kind == "parameter":
            session.set_parameter(obj.key, "radius", value)
        else:
            session.set_raw_byte(obj.key, 9, value)
    assert session.object(obj.key) == obj and not session.dirty and not session.can_undo


@pytest.mark.parametrize("offset", [-1, 0, 1, 2, 7, 255])
def test_raw_editor_protects_structure_and_coordinate_fields(session: EditSession, offset: int) -> None:
    with pytest.raises(EditError):
        session.set_raw_byte((5, 0), offset, 255)
    assert not session.dirty


def test_unknown_padding_and_signed_array_values_can_be_changed(session: EditSession) -> None:
    checkpoint = next(o for o in session.current_map(5).objects if o.definition.behavior_id == 13)
    session.set_raw_byte(checkpoint.key, 0x1B, 0xA5)
    assert session.object(checkpoint.key).raw_data[0x1B] == 0xA5
    assert session.object(checkpoint.key).value("unk1B") == 0xA5
    session.set_parameter(checkpoint.key, "unkB", -128)
    assert session.object(checkpoint.key).raw_data[0x0B] == 128
    ai = next(o for i in range(138) for o in session.current_map(i).objects if o.definition.behavior_id == 16)
    session.set_parameter(ai.key, "adjacent", (1, 2, 255, 3))
    assert session.object(ai.key).value("adjacent") == (1, 2, 255, 3)
    with pytest.raises(EditError):
        session.set_parameter(ai.key, "adjacent", (1, 2))


def test_unknown_halfword_and_raw_bytes_stay_big_endian(session: EditSession) -> None:
    obj, parameter = next((obj, p) for map_id in range(138) for obj in session.current_map(map_id).objects
                          for p in obj.parameters if p.name.startswith("unk") and p.format in ("h", "H"))
    session.set_raw_byte(obj.key, parameter.offset, 0x80)
    session.set_raw_byte(obj.key, parameter.offset+1, 0)
    assert session.object(obj.key).value(parameter.name) == (-32768 if parameter.format == "h" else 32768)
    session.set_parameter(obj.key, parameter.name, -1 if parameter.format == "h" else 65535)
    raw = session.object(obj.key).raw_data
    assert raw[parameter.offset:parameter.offset+2] == b"\xff\xff"
    assert raw[:parameter.offset] == obj.raw_data[:parameter.offset]
    assert raw[parameter.offset+2:] == obj.raw_data[parameter.offset+2:]


def test_project_round_trip_dirty_checkpoint_and_base_protection(session: EditSession, tmp_path: Path) -> None:
    obj = session.current_map(5).objects[0]
    session.set_position(obj.key, (12, 34, 56))
    session.set_raw_byte(obj.key, 8, 0xFF)
    project = session.save_project(tmp_path / "experiment.dkrproj", 5)
    assert not session.dirty
    loaded = EditSession.load_project(project)
    assert loaded.object(obj.key) == session.object(obj.key)
    assert loaded.selected_level == 5 and not loaded.dirty
    assert not loaded.can_undo
    session.undo()
    assert session.dirty
    session.redo()
    assert not session.dirty
    assert loaded.rom.source_path == session.rom.source_path
    with pytest.raises(EditError):
        session.save_rom(session.rom.source_path)


@pytest.mark.parametrize("variant", ["version", "base", "duplicate", "prefix", "overflow", "hash", "object_id", "map_id", "level"])
def test_malformed_projects_rejected(session: EditSession, tmp_path: Path, variant: str) -> None:
    session.set_position((5, 0), (12, 34, 56))
    document = session.project_document()
    edit = document["edits"][0]
    if variant == "version": document["version"] = 999
    elif variant == "base": document["base_rom"]["sha1"] = "bad"
    elif variant == "duplicate": document["edits"].append(edit.copy())
    elif variant == "prefix": edit["bytes"][0]["offset"] = 0
    elif variant == "overflow": edit["bytes"][0]["value"] = 256
    elif variant == "hash": edit["base_entry_sha1"] = "bad"
    elif variant == "object_id": edit["object_id"] = -1
    elif variant == "map_id": edit["map_id"] = 138
    elif variant == "level": document["selected_level"] = -1
    path = tmp_path / "invalid.dkrproj"
    path.write_text(json.dumps(document))
    with pytest.raises(EditError):
        EditSession.load_project(path)


def test_rebuilt_rom_reloads_edits_and_preserves_all_other_assets(session: EditSession, rom: RomImage, tmp_path: Path) -> None:
    for map_id in range(138):
        objects = session.current_map(map_id).objects
        if objects:
            obj = objects[0]
            x, y, z = obj.position
            session.set_position(obj.key, (x + 1 if x < 32767 else x - 1, y, z))
    # Exercise every unknown byte in a representative checkpoint too.
    checkpoint = next(o for o in session.current_map(5).objects if o.definition.behavior_id == 13)
    session.set_raw_byte(checkpoint.key, 27, 0xFF)
    output = session.save_rom(tmp_path / "experiment.z64")
    rebuilt = output.read_bytes()
    assert len(rebuilt) == len(rom.data)
    assert n64_checksums(rebuilt) == struct.unpack_from(">2I", rebuilt, 0x10)
    parsed = RomImage(rebuilt, "z64", parse_asset_lut(rebuilt, LUT_START, LUT_END), output)
    for section in range(50):
        if section not in (20, 21):
            assert parsed.section(section) == rom.section(section)
    for map_id in range(138):
        data = parsed.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id, decompress=True)
        current = session.current_map(map_id)
        assert data == current.header + b"".join(o.raw_data for o in current.objects) + current.padding
        if map_id not in session.modified_maps:
            assert parsed.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id) == rom.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id)
    assert rebuilt[:0x10] == rom.data[:0x10]
    assert rebuilt[0x18:LUT_START] == rom.data[0x18:LUT_START]
    assert hashlib.sha1(rom.source_path.read_bytes()).hexdigest() == REV1_SHA1
    with pytest.raises(AssetError):
        RomImage.from_bytes(rebuilt)  # Stock identity verification stays strict.


def test_invalid_checksum_input_and_modified_base_rejected(rom: RomImage) -> None:
    with pytest.raises(EditError): n64_checksums(b"")
    data = bytearray(rom.data); data[0x40] ^= 1
    with pytest.raises(EditError): n64_checksums(data)
    with pytest.raises(EditError): EditSession(RomImage(bytes(data), "z64", rom.sections))


def test_real_slot_growth_relocates_assets_and_preserves_rom_tail(session: EditSession, rom: RomImage) -> None:
    # Found by recompressing each map after a one-unit move: map95 grows16 bytes.
    obj = session.current_map(95).objects[0]
    session.set_position(obj.key, (obj.position[0]+1, obj.position[1], obj.position[2]))
    rebuilt = session.build_rom()
    spans = parse_asset_lut(rebuilt, LUT_START, LUT_END)
    assert spans[21].size == rom.sections[21].size+16
    assert spans[22].start == rom.sections[22].start+16
    assert spans[-1].end == rom.sections[-1].end+16
    assert rebuilt[spans[-1].end:] == rom.data[spans[-1].end:]
    for index in range(22, 50):
        assert rebuilt[spans[index].start:spans[index].end] == rom.data[rom.sections[index].start:rom.sections[index].end]


@pytest.mark.parametrize("kind", ["project", "rom"])
def test_failed_atomic_save_preserves_previous_file(session: EditSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    session.set_position((5, 0), (100, 200, 300))
    destination = tmp_path / ("prior.dkrproj" if kind == "project" else "prior.z64")
    destination.write_bytes(b"previous file")

    def fail_replace(self: Path, target: Path) -> Path:
        raise PermissionError("locked destination")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError):
        (session.save_project if kind == "project" else session.save_rom)(destination)
    assert destination.read_bytes() == b"previous file"
    assert sorted(p.name for p in tmp_path.iterdir()) == [destination.name]
    assert session.dirty and session.project_path is None


def test_export_capacity_failure_leaves_destination_untouched(session: EditSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session.set_position((5, 0), (1, 2, 3))
    path = tmp_path / "prior.z64"; path.write_bytes(b"prior")
    monkeypatch.setattr("src.core.editing.compress_object_map", lambda data: bytes(len(session.rom.data)))
    with pytest.raises(EditError, match="padding"):
        session.save_rom(path)
    assert path.read_bytes() == b"prior"


def test_project_can_use_relocated_verified_base(session: EditSession, tmp_path: Path) -> None:
    session.set_position((5, 0), (1, 2, 3))
    document = session.project_document()
    document["base_rom"]["path"] = "missing-base.z64"
    path = tmp_path / "relocated.dkrproj"; path.write_text(json.dumps(document))
    with pytest.raises(FileNotFoundError):
        EditSession.load_project(path)
    loaded = EditSession.load_project(path, base_path=session.rom.source_path)
    assert loaded.object((5, 0)).position == (1, 2, 3)
