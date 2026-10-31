"""Model material byte isolation, safety boundaries, projects and in-memory export."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import struct
import numpy as np
import pytest

from src.core.editing import EditSession, EditError, n64_checksums
from src.core.materials import (MaterialEdit, edit_materials, editable_mask, validate_material_edit,
    pick_track_face, batch_for_face, slot_uses, EDITABLE_BATCH_FLAGS)
from src.core.level_model import LevelModel
from src.core.textures import load_model_textures, model_uvs
from src.core.exporter import export_obj
from src.core.rom import RomImage, AssetType, LUT_START, LUT_END, REV1_SHA1, parse_asset_lut
from src.core.research import compare_sessions


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


@pytest.fixture(scope="module")
def session(rom: RomImage) -> EditSession:
    return EditSession(rom)


def footprint(a: bytes, b: bytes) -> set[int]:
    assert len(a) == len(b)
    return {i for i, (x, y) in enumerate(zip(a, b)) if x != y}


def assert_geometry_preserved(a: LevelModel, b: LevelModel) -> None:
    assert (a.bounds, a.stored_bounds, a.bsp_nodes, a.vertex_count, a.triangle_count, a.byte_size) == (b.bounds, b.stored_bounds, b.bsp_nodes, b.vertex_count, b.triangle_count, b.byte_size)
    for x, y in zip(a.segments, b.segments):
        assert x.terminal_batch == y.terminal_batch and x.bounds == y.bounds and x.opaque_batch_count == y.opaque_batch_count
        np.testing.assert_array_equal(x.vertices, y.vertices)
        np.testing.assert_array_equal(x.indices, y.indices)
        assert [(v.vertices_offset, v.faces_offset, v.vertex_override, v.misc_data) for v in x.batches] == [(v.vertices_offset, v.faces_offset, v.vertex_override, v.misc_data) for v in y.batches]


def test_noop_all_55_models_keeps_full_bytes_and_legacy_metadata(session: EditSession) -> None:
    mismatches = 0
    for model_id in range(session.rom.count(AssetType.LEVEL_MODELS)):
        model = session.track_model(model_id)
        raw = model.raw_data
        assert edit_materials(raw, (), session.material_references) == raw
        for slot, info in enumerate(model.textures):
            h = session.material_references[info.texture_id].header
            mismatches += (info.width, info.height, info.format) != (h.width, h.height, h.raw[2])
            # Unchanged texture assignment must never normalize stored metadata.
            if slot == 0:
                assert edit_materials(raw, (MaterialEdit("texture", (slot,), info.texture_id),), session.material_references) == raw
        assert not np.any(np.bitwise_xor(np.frombuffer(raw, np.uint8), np.frombuffer(model.raw_data, np.uint8)))
    assert session.rom.count(AssetType.LEVEL_MODELS) == 55 and mismatches == 609
    assert not session.dirty and session.build_rom() is session.rom.data


def test_each_writer_changes_only_verified_material_bytes(session: EditSession) -> None:
    model = session.track_model(5)
    raw = model.raw_data
    segment = 0
    s = model.segments[segment]
    seg_offset = struct.unpack_from(">I", raw, 4)[0]
    vertices, faces, _, batches = struct.unpack_from(">4I", raw, seg_offset)
    textures = struct.unpack_from(">I", raw)[0]
    cases = ((MaterialEdit("surface", (0,), (model.textures[0].surface_type + 1) % 19), {textures + 7}),
             (MaterialEdit("uv", (0, 0), (-32768, 32767, -32, 32, 1024, -2048)), set(range(faces + 4, faces + 16))),
             (MaterialEdit("color", (0, 0), (12, 34, 56, 78)), set(range(vertices + 6, vertices + 10))),
             (MaterialEdit("backface", (0, 0), int(not s.triangle_flags[0] & 0x40)), {faces}),
             (MaterialEdit("frame", (0, 0), 4), {batches + 7}),
             (MaterialEdit("flags", (0, 0), s.batches[0].flags ^ 0x100), {batches + 10}))
    for edit, allowed in cases:
        new_raw = edit_materials(raw, (edit,), session.material_references)
        assert footprint(raw, new_raw) and footprint(raw, new_raw) <= allowed
        new = LevelModel.from_bytes(new_raw)
        assert_geometry_preserved(model, new)
        assert np.all((np.frombuffer(raw, np.uint8) ^ np.frombuffer(new_raw, np.uint8)) & ~editable_mask(model) == 0)
    # The loader encoding is deliberately preserved and previewed, not rewritten.
    new = LevelModel.from_bytes(edit_materials(raw, (MaterialEdit("color", (0, 0), (1, 1, 91, 255)),), session.material_references))
    assert new.segments[0].render_colors[0].tolist() == [128, 128, 128, 91]


def test_reference_assignment_restores_legacy_metadata_and_pass_limits(session: EditSession) -> None:
    m = session.track_model(5)
    old = m.textures[0]
    raw = m.raw_data
    refs = session.material_references
    compatible = next(ref.texture_id for ref in refs if ref.translucent == refs[old.texture_id].translucent and ref.texture_id != old.texture_id)
    new = edit_materials(raw, (MaterialEdit("texture", (0,), compatible),), refs)
    t = LevelModel.from_bytes(new).textures[0]
    h = refs[compatible].header
    assert (t.texture_id, t.width, t.height, t.format, t.surface_type) == (compatible, h.width, h.height, h.raw[2], old.surface_type)
    restored = edit_materials(new, (MaterialEdit("texture", (0,), old.texture_id),), refs, original=raw)
    assert restored == raw
    incompatible = next(ref.texture_id for ref in refs if ref.translucent != refs[old.texture_id].translucent)
    assert slot_uses(m, 0)
    with pytest.raises(ValueError, match="pass"):
        edit_materials(raw, (MaterialEdit("texture", (0,), incompatible),), refs)
    texture_ptr = struct.unpack_from(">I", raw)[0]
    bad = bytearray(raw); bad[texture_ptr + 4] ^= 1
    with pytest.raises(ValueError, match="independently"):
        validate_material_edit(raw, bytes(bad), refs)


@pytest.mark.parametrize("edit", [MaterialEdit("surface", (0,), -1), MaterialEdit("surface", (0,), 19),
    MaterialEdit("texture", (0,), 999999), MaterialEdit("uv", (0, 0), (0, 0, 0, 0, 0, 32768)),
    MaterialEdit("uv", (0, 0), (0, 0)), MaterialEdit("color", (0, 0), (0, 0, 0, 256)),
    MaterialEdit("color", (0, 0), (1, 2, 3)), MaterialEdit("batch_texture", (0, 0), 254),
    MaterialEdit("frame", (0, 0), 256), MaterialEdit("flags", (0, 0), 0xFFFFFFFF),
    MaterialEdit("backface", (0, 0), 2), MaterialEdit("uv", (-1, 0), (0,) * 6)])
def test_invalid_or_unsupported_edits_are_rejected_atomically(session: EditSession, edit: MaterialEdit) -> None:
    raw = session.track_model(5).raw_data
    with pytest.raises(ValueError):
        edit_materials(raw, (MaterialEdit("surface", (0,), 1), edit), session.material_references)
    assert not session.dirty


def test_mask_protects_xyz_indices_offsets_tail_and_collision(session: EditSession) -> None:
    m = session.track_model(5)
    raw = m.raw_data
    seg = struct.unpack_from(">I", raw, 4)[0]
    vertex, face, _, batches = struct.unpack_from(">4I", raw, seg)
    offsets = (0, 4, 0x18, 0x20, 0x48, seg + 0x1C, seg + 0x14, vertex, face + 1, batches + 2, batches + 6,
               batches + len(m.segments[0].batches) * 12 + 7)
    for offset in offsets:
        bad = bytearray(raw); bad[offset] ^= 1
        with pytest.raises(ValueError, match="protected"):
            validate_material_edit(raw, bytes(bad), session.material_references)
    mask = editable_mask(m)
    for offset in np.flatnonzero(mask == 0)[::max(1, len(raw)//70)]:
        bad = bytearray(raw); bad[offset] ^= 1
        with pytest.raises(ValueError): validate_material_edit(raw, bytes(bad), session.material_references)


def test_model_history_project_export_and_other_sections_unchanged(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    original = s.track_model(5)
    edits = (MaterialEdit("surface", (0,), 2), MaterialEdit("uv", (0, 0), (-32, 64, 128, -256, 512, 1024)), MaterialEdit("color", (0, 0), (210, 30, 80, 255)))
    assert s.edit_track_materials(5, edits) and s.last_asset_key == (AssetType.LEVEL_MODELS, 5)
    updated = s.current_asset(AssetType.LEVEL_MODELS, 5)
    assert s.can_undo and not s.can_redo
    s.undo(); assert not s.dirty and s.current_asset(AssetType.LEVEL_MODELS, 5) == original.raw_data
    s.redo(); assert s.current_asset(AssetType.LEVEL_MODELS, 5) == updated
    project = s.save_project(tmp_path / "material.dkrproj", 5)
    loaded = EditSession.load_project(project)
    assert not compare_sessions(s, loaded) and not loaded.dirty
    assert_geometry_preserved(original, loaded.track_model(5))
    report = s.export_report()
    assert len(report.assets) == 1 and report.assets[0].section == 27 and any("Ancient Lake" in use for use in report.assets[0].levels)
    rebuilt_bytes = loaded.build_rom()  # Memory only: no gameplay/sample ROM.
    rebuilt = RomImage(rebuilt_bytes, "z64", parse_asset_lut(rebuilt_bytes, LUT_START, LUT_END))
    assert rebuilt.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True) == updated
    for section in range(50):
        if section not in (26, 27):
            assert rebuilt.section(section) == rom.section(section)
    for index in range(55):
        if index != 5:
            assert rebuilt.read_asset(AssetType.LEVEL_MODELS, index) == rom.read_asset(AssetType.LEVEL_MODELS, index)
    assert len(rebuilt_bytes) == len(rom.data) and struct.unpack_from(">II", rebuilt_bytes, 16) == n64_checksums(rebuilt_bytes)
    assert hashlib.sha1(rom.source_path.read_bytes()).hexdigest() == REV1_SHA1
    loaded.revert_track_materials(5)
    assert loaded.build_rom() == rom.data
    loaded.undo(); assert loaded.current_asset(AssetType.LEVEL_MODELS, 5) == updated


def test_batch_reference_flags_none_guard_and_duplicate_operations(session: EditSession) -> None:
    m = session.track_model(5)
    b = m.segments[0].batches[0]
    for slot in range(len(m.textures)):
        if slot == b.texture_index:
            continue
        try:
            raw = edit_materials(m.raw_data, (MaterialEdit("batch_texture", (0,0), slot),), session.material_references)
        except ValueError:
            continue
        offset = struct.unpack_from(">I", m.raw_data, 4)[0]
        batches = struct.unpack_from(">I", m.raw_data, offset + 12)[0]
        assert footprint(m.raw_data, raw) == {batches}
        assert LevelModel.from_bytes(raw).segments[0].batches[0].texture_index == slot
        break
    else:
        pytest.fail("Expected another compatible existing material slot")
    with pytest.raises(ValueError, match="untextured"):
        edit_materials(m.raw_data, (MaterialEdit("batch_texture", (0,0), 255),), session.material_references)
    for mask in (0x10, 0x100, 0x200, 0x800, 0x4000, 0x08000000):
        raw = edit_materials(m.raw_data, (MaterialEdit("flags", (0,0), b.flags ^ mask),), session.material_references)
        assert LevelModel.from_bytes(raw).segments[0].batches[0].flags == b.flags ^ mask
    with pytest.raises(ValueError, match="Duplicate"):
        edit_materials(m.raw_data, (MaterialEdit("surface", (0,), 2), MaterialEdit("surface", (0,), 4)), session.material_references)


def test_model_growth_budget_and_mixed_asset_relocation(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    m = s.track_model(5)
    rng = np.random.default_rng(1414)
    edits = tuple(MaterialEdit("color", (seg.index, i), tuple(map(int, rng.integers(0,256,4))))
                  for seg in m.segments for i in range(seg.vertex_count))
    s.edit_track_materials(5, edits, "Change existing vertex colors")
    report = s.export_report()
    assert report.growth_bytes > 0 and report.can_export
    assert all(b.edited_start == b.original_start + report.growth_bytes for b in report.sections[28:])
    obj = s.object((95,0)); s.set_position(obj.key, (obj.position[0]+1,*obj.position[1:]))
    s.set_level_field(5, "laps", 2)
    s.set_note((5,48), "unk19", "Material experiment")
    saved = EditSession.load_project(s.save_project(tmp_path / "mixed.dkrproj", 5))
    data = saved.build_rom()
    rebuilt = RomImage(data, "z64", parse_asset_lut(data, LUT_START, LUT_END))
    assert rebuilt.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True) == saved.track_model(5).raw_data
    assert rebuilt.read_asset(AssetType.LEVEL_HEADERS, 5) == saved.level_header(5).raw_data
    assert rebuilt.read_asset(AssetType.LEVEL_OBJECT_MAPS, 95, decompress=True) == s._modified[95]
    assert {asset.section for asset in saved.export_report().assets} == {21, 23, 27}
    for section in range(50):
        if section not in (20, 21, 23, 26, 27):
            assert rebuilt.section(section) == rom.section(section)
    assert not compare_sessions(s, saved)
    # Give the read-only preflight a non-padding tail immediately after assets.
    protected = bytearray(rom.data); protected[rom.sections[-1].end] = 1
    saved.rom = RomImage(bytes(protected), "z64", rom.sections, rom.source_path)
    saved._report_cache = None
    assert not saved.export_report().can_export
    with pytest.raises(EditError, match="padding"):
        saved.build_rom()


def test_material_obj_uv_color_and_texture_reference_consistency(session: EditSession, tmp_path: Path) -> None:
    raw = session.track_model(5).raw_data
    edits = (MaterialEdit("uv", (0, 0), (-32, 64, 128, -256, 512, 1024)), MaterialEdit("color", (0, 0), (210, 30, 80, 255)))
    m = LevelModel.from_bytes(edit_materials(raw, edits, session.material_references))
    textures = load_model_textures(session.rom, m)
    uv = model_uvs(m, textures, obj=True)
    result = export_obj(m, tmp_path / "materials.obj", textures=textures)
    text = result.path.read_text()
    uv_line = next(line for line in text.splitlines() if line.startswith("vt "))
    np.testing.assert_allclose([float(v) for v in uv_line.split()[1:]], uv[0, 0], rtol=1e-5)
    assert "# DKR segment 0 batch 0 texture_slot" in text
    first_vertex = next(line for line in text.splitlines() if line.startswith("v "))
    np.testing.assert_allclose([float(v) for v in first_vertex.split()[-3:]], np.array([210,30,80])/255, atol=1e-5)
    assert result.material_path.exists() and result.texture_paths and all(path.exists() for path in result.texture_paths)


@pytest.mark.parametrize("variant", ("geometry", "flags", "encoding", "hash", "legacy", "duplicate", "size"))
def test_project_model_overlay_cannot_bypass_material_boundaries(rom: RomImage, tmp_path: Path, variant: str) -> None:
    s = EditSession(rom)
    s.edit_track_materials(5, (MaterialEdit("surface", (0,), 2),))
    doc = s.project_document(5)
    edit = doc["asset_edits"][0]
    if variant == "geometry": edit["bytes"].append({"offset": 0x26, "value": 10})
    if variant == "flags":
        raw = s.track_model(5).raw_data
        seg = struct.unpack_from(">I", raw, 4)[0]
        batches = struct.unpack_from(">I", raw, seg + 12)[0]
        edit["bytes"].append({"offset": batches + 11, "value": raw[batches + 11] ^ 1})
    if variant == "encoding": edit["encoding"] = "raw"
    if variant == "hash": edit["base_asset_sha1"] = "bad"
    if variant == "legacy": doc["version"] = 3
    if variant == "duplicate": doc["asset_edits"].append(dict(edit))
    if variant == "size": edit["bytes"].append({"offset": len(s.track_model(5).raw_data), "value": 0})
    path = tmp_path / "invalid.dkrproj"; path.write_text(json.dumps(doc))
    with pytest.raises(EditError): EditSession.load_project(path)


def test_face_picking_nearest_hidden_and_isolated_geometry(session: EditSession) -> None:
    model = session.track_model(5)
    for s in model.segments:
        if not s.triangle_count:
            continue
        points = s.vertices[s.indices[0]].astype(np.float64)
        normal = np.cross(points[1]-points[0], points[2]-points[0])
        if np.linalg.norm(normal) < .001 or s.batches[batch_for_face(model, s.index, 0)].hidden:
            continue
        normal /= np.linalg.norm(normal)
        center = points.mean(axis=0)
        assert pick_track_face(model, center + normal*.01, -normal, segment=s.index) == (s.index, 0)
        assert pick_track_face(model, center - normal*.01, normal, segment=s.index) == (s.index, 0)
        assert pick_track_face(model, center + normal*.01, -normal, segment=s.index, cull_backfaces=True) == (s.index, 0)
        if not s.triangle_flags[0] & 0x40:
            assert pick_track_face(model, center - normal*.01, normal, segment=s.index, cull_backfaces=True) != (s.index, 0)
            double_sided = s.triangle_flags.copy(); double_sided[0] |= 0x40
            two_sided_model = replace(model, segments=tuple(replace(seg, triangle_flags=double_sided) if seg.index == s.index else seg for seg in model.segments))
            assert pick_track_face(two_sided_model, center - normal*.01, normal, segment=s.index, cull_backfaces=True) == (s.index, 0)
        new = replace(model, segments=tuple(replace(seg, batches=tuple(replace(b, flags=b.flags | 0x100) for b in seg.batches)) for seg in model.segments))
        assert pick_track_face(new, center + normal, -normal) is None
        assert pick_track_face(model, center + normal, -normal, segment=9999) is None
        break
    assert pick_track_face(model, np.zeros(3), np.zeros(3)) is None
