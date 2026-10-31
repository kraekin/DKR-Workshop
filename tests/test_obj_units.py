"""Compact track exchange restores placement, precision and game-space editing."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.exporter import export_obj
from src.core.level_model import LevelModel, load_level_model
from src.core.obj_units import GAME_UNITS_PER_OBJ_UNIT, OBJ_UNITS_PER_GAME_UNIT
from src.core.placement import TerrainSurface
from src.core.rom import AssetType, LUT_START, LUT_END, RomImage, parse_asset_lut
from src.core.textures import load_model_textures, model_uvs
from src.core.track_import import ImportOptions, compile_obj, default_materials, parse_obj, read_obj
from src.core.track_segments import compile_segmented_obj, collision_helper_faces, collision_query

ROOT = Path(__file__).resolve().parents[1]
COMPACT_QUAD = '''usemtl slot_6
v -55 1.5 -110
v -55 1.5 -100
v -45 1.5 -100
v -45 1.5 -110
vt 0 0
vt 0 1
vt 1 1
vt 1 0
f 1/1 2/2 3/3
f 1/1 3/3 4/4
'''


@pytest.fixture(scope='module')
def rom() -> RomImage:
    return RomImage.from_file(ROOT/'Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64')


@pytest.fixture(scope='module')
def source(rom: RomImage) -> EditSession:
    return EditSession(rom)


@pytest.mark.parametrize('index', range(55))
def test_all_stock_exports_are_compact_without_mutation(rom: RomImage, tmp_path: Path, index: int) -> None:
    model = load_level_model(rom, index)
    before = model.flat_vertices.copy(), model.indices.copy(), model.raw_data
    output = export_obj(model, tmp_path/f'{index}.obj')
    # Stock assets can contain faces the stricter custom-topology reader refuses.
    rows = [line.split() for line in output.path.read_text().splitlines()]
    vertices = np.asarray([[float(v) for v in row[1:]] for row in rows if row and row[0] == 'v'])
    xyz = vertices[:, :3]
    np.testing.assert_allclose(xyz, before[0][:, :3].astype(np.float64)/100, rtol=0, atol=1e-10)
    np.testing.assert_array_equal(np.rint(xyz*100), before[0][:, :3])
    helpers = collision_helper_faces(model)
    expected = [tuple(face+part.vertex_base) for part in model.segments
                for i, face in enumerate(part.indices) if (part.index, i) not in helpers]
    assert [tuple(int(c)-1 for c in row[1:]) for row in rows if row and row[0] == 'f'] == expected
    np.testing.assert_allclose(vertices[:, 3:6], before[0][:, 3:6], atol=1e-6)
    np.testing.assert_array_equal(model.flat_vertices, before[0])
    np.testing.assert_array_equal(model.indices, before[1])
    assert model.raw_data == before[2]


def test_export_retains_signed16_extremes_and_single_game_unit_steps(source: EditSession, tmp_path: Path) -> None:
    model = source.track_model(5)
    vertices = model.flat_vertices.copy()
    vertices[:3, :3] = ((-32768, 0, 32767), (-32767, -1, 32766), (1, 2, -2))
    output = export_obj(replace(model, flat_vertices=vertices), tmp_path/'limits.obj')
    xyz = np.asarray(read_obj(output.path, max_faces=6000).vertices)[:3]
    np.testing.assert_array_equal(np.rint(xyz*100), vertices[:3, :3])
    assert xyz[1, 0]-xyz[0, 0] == pytest.approx(.01)


@pytest.mark.parametrize('segmented', (False, True))
@pytest.mark.parametrize('scale', (100., 50.))
def test_import_multiplier_applies_once_then_game_offset_and_rounding(source: EditSession, segmented: bool, scale: float) -> None:
    # One-game-unit X separation survives conversion; Y is rounded after offset.
    mesh = parse_obj('v -45 .154 -70\nv -45 .154 -69\nv -44.99 .154 -70\nf 1 2 3')
    compiler = compile_segmented_obj if segmented else compile_obj
    options = ImportOptions(scale, (3, .4, -7))
    result = compiler(mesh, source.track_base(5), source.material_references, {'(default)': 6}, options)
    model = LevelModel.from_bytes(result.raw)
    actual = {tuple(p) for part in model.segments for p in part.vertices}
    expected = {tuple(p) for p in np.rint(np.asarray(mesh.vertices)*scale+(3, .4, -7))}
    assert actual == expected
    assert next(iter(actual))[1] == (16 if scale == 100 else 8)
    assert all(t.surface_type == source.track_model(5).textures[i].surface_type
               for i, t in enumerate(model.textures))


@pytest.mark.parametrize('segmented', (False, True))
@pytest.mark.parametrize('position', ('327.68', '-327.69'))
def test_default_import_rejects_out_of_range_after_conversion(source: EditSession, segmented: bool, position: str) -> None:
    mesh = parse_obj(f'v {position} 0 0\nv {position} 0 1\nv 0 0 0\nf 1 2 3')
    compiler = compile_segmented_obj if segmented else compile_obj
    with pytest.raises(ValueError, match='signed16'):
        compiler(mesh, source.track_base(5), source.material_references, {'(default)': 6})


def test_default_units_agree() -> None:
    assert ImportOptions().scale == GAME_UNITS_PER_OBJ_UNIT == 100
    assert OBJ_UNITS_PER_GAME_UNIT == .01


@pytest.mark.parametrize('segmented', (False, True))
def test_compact_textured_roundtrip_history_project_and_in_memory_rom(rom: RomImage, tmp_path: Path, segmented: bool) -> None:
    session = EditSession(rom)
    compiler = compile_segmented_obj if segmented else compile_obj
    original = session.track_base(5)
    maps = {i: session.current_asset(AssetType.LEVEL_OBJECT_MAPS, i)
            for i in (5, 73)}
    mesh = parse_obj(COMPACT_QUAD)
    result = compiler(mesh, original, session.material_references, {'slot_6': 6})
    assert session.preview_track_import(5, result.raw).can_export
    assert session.track_base(5) == original and not session.dirty
    session.import_track(5, result.raw)
    model = session.track_model(5)
    assert model.bounds.minimum == (-5500, 150, -11000)
    assert model.bounds.maximum == (-4500, 150, -10000)
    terrain = TerrainSurface.from_model(model)
    assert terrain.surface_y((-5000, 300, -10500), drop=True) == 150
    if segmented:
        query = collision_query(model, np.array([[-5000, 300, -10500]]), np.array([[-5000, 100, -10500]]))
        assert query.complete and query.required_entries > 1
    textures = load_model_textures(rom, model)
    exported = export_obj(model, tmp_path/'compact.obj', textures=textures)
    incoming = read_obj(exported.path, max_faces=6000)
    np.testing.assert_allclose(np.asarray(incoming.vertices)*100, model.flat_vertices[:, :3], atol=1e-9)
    np.testing.assert_allclose(incoming.uvs, model_uvs(model, textures, obj=True).reshape(-1, 2), atol=1e-7)
    rebuilt = compiler(incoming, original, session.material_references, default_materials(incoming, model))
    assert rebuilt.raw == result.raw  # Includes surfaces, winding, colors, collision and bounds.
    path = tmp_path/'compact.dkrproj'
    session.save_project(path, selected_level=5)
    loaded = EditSession.load_project(path)
    assert loaded.track_base(5) == result.raw
    assert all(loaded.current_asset(AssetType.LEVEL_OBJECT_MAPS, i) == raw for i, raw in maps.items())
    data = loaded.build_rom()
    output = RomImage(data, 'z64', parse_asset_lut(data, LUT_START, LUT_END))
    assert output.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True) == result.raw
    assert all(rom.section(section) == output.section(section) for section in AssetType
               if int(section) < len(rom.sections) and int(section) not in (26, 27))
    session.undo()
    assert session.track_base(5) == original and session.dirty  # Saved state contains the import.
    session.redo()
    assert session.track_base(5) == result.raw
