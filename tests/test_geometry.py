"""Stock-shape dependencies, protected edits, project migration and ROM round trips."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import struct

import numpy as np
import pytest

from src.core.geometry import (TRACK_HEAP, geometry_profile, copy_geometry, geometry_changed,
    validate_geometry, move_vertices, linked_vertices, runtime_track_bytes, verify_geometry_stream, collision_base_planes)
from src.core.level_model import LevelModel, load_level_model
from src.core.editing import EditSession, n64_checksums, compress_asset
from src.core.materials import MaterialEdit
from src.core.minimap import copy_minimap
from src.core.placement import TerrainSurface
from src.core.rom import RomImage, AssetType, LUT_START, LUT_END, parse_asset_lut
from src.renderer.camera import Camera, pick_track_vertex, project_point


def synthetic() -> bytes:
    """Two triangles with duplicated batch vertices, known adjacency and generous bounds."""
    raw = bytearray(0x150)
    struct.pack_into('>6I', raw, 0, 0x50, 0x58, 0x12C, 0, 0, 0x148)
    struct.pack_into('>2h', raw, 0x18, 1, 1)
    struct.pack_into('>6h', raw, 0x3C, -200, 200, -200, 200, -200, 200)
    struct.pack_into('>i', raw, 0x48, len(raw))
    struct.pack_into('>IBBBb', raw, 0x50, 42, 32, 32, 0, 0)
    struct.pack_into('>7I', raw, 0x58, 0xF0, 0xD0, 0, 0xA0, 0, 0x138, 0)
    struct.pack_into('>3h', raw, 0x74, 6, 2, 2)
    for i in range(3):
        struct.pack_into('>BbhhBBI', raw, 0xA0+i*12, 0, 0, i*3, i, 0, 0, 0)
    for i in range(2):
        struct.pack_into('>4B6h', raw, 0xD0+16*i, 0, 0, 1, 2, *([0]*6))
    for i, point in enumerate(((0,0,0), (0,0,100), (100,0,0), (100,0,0), (0,0,100), (100,0,100))):
        struct.pack_into('>3h4B', raw, 0xF0+10*i, *point, 255, 255, 255, 255)
    struct.pack_into('>6h', raw, 0x12C, -200, -200, -200, 200, 200, 200)
    struct.pack_into('>8H', raw, 0x138, 0,0,1,0, 1,0,1,1)
    return bytes(raw)


@pytest.fixture(scope='module')
def rom() -> RomImage:
    for path in Path.cwd().glob('*.z64'):
        try:
            return RomImage.from_file(path)
        except ValueError:
            pass
    pytest.skip('Original Rev1 ROM unavailable')


def test_welded_positions_preserve_facets_bounds_topology_colors_and_exact_noop() -> None:
    raw = synthetic()
    profile = geometry_profile(raw)
    assert linked_vertices(profile, ((0,1),)) == ((0,1), (0,4))
    assert move_vertices(raw, raw, ((0,1),), (0,0,0)) == raw
    changed = move_vertices(raw, raw, ((0,1),), (0,20,0))
    a, b = LevelModel.from_bytes(raw), LevelModel.from_bytes(changed)
    np.testing.assert_array_equal(b.segments[0].vertices[[1,4]], [[0,20,100]]*2)
    assert copy_geometry(changed, raw) == raw
    assert geometry_changed(raw, changed)
    assert runtime_track_bytes(a) == runtime_track_bytes(b)
    assert a.stored_bounds == b.stored_bounds and a.bsp_nodes == b.bsp_nodes
    np.testing.assert_array_equal(a.indices, b.indices)
    np.testing.assert_array_equal(a.segments[0].colors, b.segments[0].colors)
    assert raw[0x138:0x148] == changed[0x138:0x148]
    assert runtime_track_bytes(a) == 0x1D0  # align(0x150+4)=0x160; two base + five edge planes
    planes = collision_base_planes(b.segments[0].vertices[b.segments[0].indices])
    assert planes.dtype == np.float32
    assert not np.array_equal(planes, collision_base_planes(a.segments[0].vertices[a.segments[0].indices]))
    for plane, points in zip(planes, b.segments[0].vertices[b.segments[0].indices]):
        np.testing.assert_allclose(points@plane[:3]+plane[3], 0, atol=1e-5)
    np.testing.assert_allclose(np.linalg.norm(planes[:,:3],axis=1),1)


def test_unwelding_merging_degenerate_reversed_bounds_and_signed16_refused() -> None:
    raw = synthetic()
    bad = bytearray(raw)
    struct.pack_into('>h', bad, 0xF0+10+2, 20)
    with pytest.raises(ValueError, match='Coincident'): validate_geometry(raw, bytes(bad))
    for key, delta, reason in (
        ((0,0), (0,0,100), 'merge'),
        ((0,0), (50,0,50), 'degenerates'),
        ((0,0), (150,0,150), 'reverses'),
        ((0,0), (0,201,0), 'bounds'),
        ((0,0), (0,32768,0), 'signed16'),
    ):
        with pytest.raises(ValueError, match=reason): move_vertices(raw, raw, (key,), delta)
    with pytest.raises(ValueError): move_vertices(raw, raw, ((0,0),(0,0)), (0,1,0))
    with pytest.raises(ValueError): move_vertices(raw, raw, ((0,99),), (0,1,0))
    with pytest.raises(ValueError): move_vertices(raw, raw, ((0,0),), (0,True,0))


def test_water_and_unresolved_smoothing_dependencies_remain_protected() -> None:
    raw = bytearray(synthetic())
    struct.pack_into('>I', raw, 0xA8, 0x2000)
    with pytest.raises(ValueError, match='water'): move_vertices(bytes(raw), bytes(raw), ((0,1),), (0,1,0))
    raw = bytearray(synthetic())
    struct.pack_into('>H', raw, 0x138+2, 1)  # triangle1 does not share triangle0 edge0
    with pytest.raises(ValueError, match='smoothing'): move_vertices(bytes(raw), bytes(raw), ((0,0),), (0,1,0))
    raw = bytearray(synthetic())
    struct.pack_into('>I', raw, 0x58+0x14, 0xFFFFFFF0)
    with pytest.raises(ValueError, match='facet span'): geometry_profile(bytes(raw))


def test_vertex_picking_accepts_corner_margin_but_respects_hidden_faces_and_occlusion() -> None:
    model = LevelModel.from_bytes(synthetic())
    camera = Camera()
    camera.fit_bounds(np.array((-50,-50,-50),np.float32),np.array((150,50,150),np.float32),800/600)
    camera.set_view('Top')
    matrix = camera.projection_matrix(800/600) @ camera.view_matrix()
    pixel = project_point(model.segments[0].vertices[0],matrix,800,600)
    assert pick_track_vertex(model,pixel[0]-2,pixel[1],800,600,matrix,cull_backfaces=True) == (0,0)
    raw = bytearray(synthetic())
    struct.pack_into('>I',raw,0xA8,0x100)
    assert pick_track_vertex(LevelModel.from_bytes(bytes(raw)),*pixel,800,600,matrix) is None
    raw = bytearray(synthetic())
    for i, point in enumerate(((0,20,0),(0,20,100),(100,20,0)),3):
        struct.pack_into('>3h',raw,0xF0+10*i,*point)
    assert pick_track_vertex(LevelModel.from_bytes(bytes(raw)),*pixel,800,600,matrix,cull_backfaces=True) == (0,3)
    assert pick_track_vertex(model,0,0,0,0,matrix) is None


def test_preview_bytes_do_not_create_history_until_one_atomic_commit(rom: RomImage) -> None:
    session = EditSession(rom)
    raw = session.track_model(5).raw_data
    previews = [move_vertices(raw,raw,((0,0),),(0,y,0)) for y in (1,5,16)]
    assert not session.dirty and not session.can_undo
    assert session.apply_track_geometry_preview(5,previews[-1])
    assert session.undo_label == 'Drag track geometry'
    assert session._cursor == 1
    session.undo()
    assert not session.dirty and session.track_model(5).raw_data == raw
    bad = bytearray(previews[-1])
    bad[0x25] ^= 1
    with pytest.raises(ValueError,match='preview'): session.apply_track_geometry_preview(5,bytes(bad))


@pytest.mark.parametrize('model_id', range(55))
def test_all_stock_profiles_noedit_identity_and_fixed_runtime_budget(rom: RomImage, model_id: int) -> None:
    model = load_level_model(rom, model_id)
    profile = geometry_profile(model.raw_data)
    assert copy_geometry(model.raw_data, model.raw_data) == model.raw_data
    assert not geometry_changed(model.raw_data, model.raw_data)
    assert runtime_track_bytes(model, profile.facets) <= TRACK_HEAP
    assert validate_geometry(model.raw_data, model.raw_data).raw_data == model.raw_data


def test_heap_refusal_and_track_loader_source_inflater(rom: RomImage) -> None:
    model = LevelModel.from_bytes(synthetic())
    with pytest.raises(ValueError, match='heap'): runtime_track_bytes(replace(model, byte_size=TRACK_HEAP))
    raw = load_level_model(rom, 5).raw_data
    out = move_vertices(raw, raw, ((0,0),), (0,16,0))
    verify_geometry_stream(out, compress_asset(out))


def test_stock_cross_segment_seam_moves_together_but_cannot_leave_bsp_partition(rom: RomImage) -> None:
    model = load_level_model(rom,5)
    raw = model.raw_data
    changed = LevelModel.from_bytes(move_vertices(raw,raw,((0,1),),(0,16,0)))
    for segment, vertex in ((0,1),(0,11),(2,13),(2,43)):
        np.testing.assert_array_equal(changed.segments[segment].vertices[vertex],(-5412,144,-10201))
    with pytest.raises(ValueError,match='BSP'):
        move_vertices(raw,raw,((0,1),),(0,0,-1))


def test_project_history_material_minimap_and_geometry_reverts_are_independent(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    raw = s.track_model(5).raw_data
    s.edit_track_geometry(5, ((0,0),), (0,16,0))
    geometry = s.track_model(5).raw_data
    assert s.project_document()['version'] == 8
    s.edit_track_materials(5, (MaterialEdit('color', (0,0), (12,34,56,78)),))
    s.edit_minimap(5, {'adv1_x': 123})
    s.revert_track_materials(5)
    assert copy_minimap(s.track_model(5).raw_data, raw) == geometry
    s.revert_track_geometry(5)
    assert not geometry_changed(raw, s.track_model(5).raw_data)
    assert s.project_document()['version'] == 6
    s.undo()
    assert geometry_changed(raw, s.track_model(5).raw_data)
    tree = s.add_object(68, next(t for t in s.object_catalog if t.object_id == 78), (1,2,3))
    s.set_note(tree, 'radius', 'geometry and structural overlays coexist')
    project = tmp_path/'geometry.dkrproj'
    s.save_project(project, 5)
    loaded = EditSession.load_project(project)
    assert loaded.track_model(5).raw_data == s.track_model(5).raw_data
    assert loaded.object(tree).position == (1,2,3)
    assert loaded.note(tree, 'radius').text == 'geometry and structural overlays coexist'
    assert not loaded.dirty


@pytest.mark.parametrize('version', (4,5,6,7))
def test_geometry_cannot_be_smuggled_into_legacy_projects(rom: RomImage, tmp_path: Path, version: int) -> None:
    s = EditSession(rom)
    s.edit_track_geometry(5, ((0,0),), (0,16,0))
    document = s.project_document()
    document['version'] = version
    path = tmp_path/'legacy.dkrproj'
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='protected'): EditSession.load_project(path)


def test_rejected_edit_atomic_and_derived_bytes_protected_even_in_v8(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    before = s.project_document()
    with pytest.raises(ValueError): s.edit_track_geometry(5, ((0,0),), (0,32000,0))
    assert before == s.project_document() and not s.can_undo
    s.edit_track_geometry(5, ((0,0),), (0,16,0))
    for offset in (4, 0x3C):
        document = s.project_document()
        raw = s.original_asset(AssetType.LEVEL_MODELS, 5)
        document['asset_edits'][0]['bytes'].append({'offset': offset, 'value': raw[offset]^1})
        path = tmp_path/'tampered.dkrproj'
        path.write_text(json.dumps(document))
        with pytest.raises(ValueError): EditSession.load_project(path)


def test_geometry_export_reloads_unchanged_assets_crc_obj_and_surface(rom: RomImage, tmp_path: Path) -> None:
    from src.core.exporter import export_obj
    s = EditSession(rom)
    old = s.track_model(5)
    s.edit_track_geometry(5, ((0,0),), (0,16,0))
    model = s.track_model(5)
    surface = TerrainSurface.from_model(model)
    before_surface = TerrainSurface.from_model(old)
    points = old.segments[0].vertices[old.segments[0].indices[0]]
    center = tuple(map(int,np.rint(points.mean(axis=0))))
    assert surface.surface_y(center, drop=False) != before_surface.surface_y(center, drop=False)
    output = s.build_rom()
    assert len(output) == len(rom.data)
    assert struct.unpack_from('>2I', output, 16) == n64_checksums(output)
    rebuilt = RomImage(output, 'z64', parse_asset_lut(output, LUT_START, LUT_END))
    assert load_level_model(rebuilt, 5).raw_data == model.raw_data
    for section, (a,b) in enumerate(zip(rom.sections, rebuilt.sections)):
        if section not in (26,27): assert rom.data[a.start:a.end] == output[b.start:b.end]
    for index in range(55):
        if index != 5: assert rom.read_asset(AssetType.LEVEL_MODELS,index) == rebuilt.read_asset(AssetType.LEVEL_MODELS,index)
    assert any('XYZ' in row for asset in s.export_report().assets for row in asset.changes)
    result = export_obj(model, tmp_path/'edited.obj')
    assert (tmp_path/'edited.obj').exists()
    assert old.triangle_count == model.triangle_count
    s.undo()
    assert not s.dirty and s.build_rom() is rom.data
