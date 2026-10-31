"""Object OBJ boundaries use compact units; model/clip/project bytes stay native."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.model_editing import (animation_document, edit_mesh, import_mesh_obj,
    mesh_obj, plan_models, structures)
from src.core.object_models import ObjectLibrary, ObjectModel
from src.core.object_rebuild import compile_static, rebuild_obj
from src.core.rom import AssetType, LUT_START, LUT_END, RomImage, parse_asset_lut

ROOT = Path(__file__).resolve().parents[1]
M = AssetType.OBJECT_MODELS


@pytest.fixture(scope='module')
def rom() -> RomImage:
    return RomImage.from_file(ROOT/'Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64')


@pytest.fixture(scope='module')
def library(rom: RomImage) -> ObjectLibrary:
    return ObjectLibrary(rom)


def shifted(text: str, amount: float) -> str:
    rows = []
    for line in text.splitlines():
        words = line.split()
        if words and words[0] == 'v':
            words[1] = f'{float(words[1])+amount:.12g}'
            line = ' '.join(words)
        rows.append(line)
    return '\n'.join(rows)+'\n'


def test_all390_mesh_exports_use_compact_coordinates_and_keep_source_bytes(library: ObjectLibrary) -> None:
    static_count = 0
    for i in range(390):
        model = library.model(i)
        segment = model.mesh.segments[0]
        before = segment.vertices.copy(), segment.colors.copy(), model.raw_data
        outputs = [mesh_obj(model.raw_data)]
        if library.clip_count(i) == 0:
            outputs.append(rebuild_obj(model.raw_data, library.source))
            static_count += 1
        for text in outputs:
            values = np.asarray([[float(v) for v in line.split()[1:]]
                                 for line in text.splitlines() if line.startswith('v ')])
            np.testing.assert_allclose(values[:, :3], before[0].astype(np.float64)/100, rtol=0, atol=1e-10)
            np.testing.assert_array_equal(np.rint(values[:, :3]*100), before[0])
            if values.shape[1] == 7:
                np.testing.assert_allclose(values[:, 3:], before[1]/255, rtol=0, atol=1e-9)
            assert 'Blender import/export Scale 1' in text
        np.testing.assert_array_equal(segment.vertices, before[0])
        np.testing.assert_array_equal(segment.colors, before[1])
        assert model.raw_data == before[2]
    assert static_count == 207


@pytest.mark.parametrize('index', (83, 240, 256))
@pytest.mark.parametrize('amount,game_delta', ((.004, 0), (.006, 1), (-.006, -1), (.01, 1)))
def test_reshape_rounds_after_conversion_and_keeps_reference_and_clip_units(library: ObjectLibrary, index: int, amount: float, game_delta: int) -> None:
    original = library.model(index)
    raw = import_mesh_obj(original.raw_data, shifted(mesh_obj(original.raw_data), amount))
    model = ObjectModel.from_bytes(raw, index)
    np.testing.assert_array_equal(model.mesh.segments[0].vertices,
                                  original.mesh.segments[0].vertices+(game_delta, 0, 0))
    np.testing.assert_array_equal(model.mesh.indices, original.mesh.indices)
    assert structures(raw) == structures(original.raw_data)
    for j in range(library.clip_count(index)):
        clip = library.clip(index, j)
        assert animation_document(clip.raw_data, model) == animation_document(clip.raw_data, original)


def test_fixed_exchange_preserves_signed16_limits(library: ObjectLibrary) -> None:
    original = library.model(256).raw_data
    raw = edit_mesh(original, 'vertex', 0, (-32768, -1, 32767))
    assert import_mesh_obj(raw, mesh_obj(raw)) == raw


@pytest.mark.parametrize('rebuild', (False, True))
@pytest.mark.parametrize('position', ('327.68', '-327.69'))
def test_import_refuses_out_of_range_model_units(rom: RomImage, rebuild: bool, position: str) -> None:
    raw = rom.read_asset(M, 256, decompress=True)
    if rebuild:
        text = f'v {position} 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3'
    else:
        rows = mesh_obj(raw).splitlines()
        i = next(i for i, row in enumerate(rows) if row.startswith('v '))
        rows[i] = f'v {position} 0 0'
        text = '\n'.join(rows)
    with pytest.raises(ValueError, match='signed16'):
        if rebuild:
            compile_static(rom, 256, text)
        else:
            import_mesh_obj(raw, text)


def test_static_rebuild_converts_before_rounding_material_inference_and_bounds(rom: RomImage) -> None:
    text = 'v -.014 .004 .006\nv -.014 .004 1.006\nv .006 .004 .006\nf 1 2 3'
    result = compile_static(rom, 256, text)
    model = ObjectModel.from_bytes(result.raw)
    np.testing.assert_array_equal(model.mesh.segments[0].vertices,
                                  [(-1, 0, 1), (-1, 0, 101), (1, 0, 1)])
    assert compile_static(rom, 256, rebuild_obj(result.raw, rom), appearance=result.raw).raw == result.raw


def test_compact_model_edit_history_project_and_rom_do_not_rescale_clips_or_other_assets(rom: RomImage, tmp_path: Path) -> None:
    session = EditSession(rom)
    original = session.current_asset(M, 240)
    raw = import_mesh_obj(original, shifted(mesh_obj(original), .01))
    plan = plan_models(session, {(M, 240): raw})
    assert plan.report.can_export and not session.dirty
    session.apply_models(plan)
    session.undo()
    assert session.current_asset(M, 240) == original
    session.redo()
    assert session.current_asset(M, 240) == raw
    path = session.save_project(tmp_path/'compact-model.dkrproj')
    loaded = EditSession.load_project(path)
    assert loaded.current_asset(M, 240) == raw
    data = loaded.build_rom()
    output = RomImage(data, 'z64', parse_asset_lut(data, LUT_START, LUT_END))
    assert output.read_asset(M, 240, decompress=True) == raw
    for section in AssetType:
        if int(section) < len(rom.sections) and int(section) not in (28, 29):
            assert output.section(section) == rom.section(section)
    for i in range(390):
        if i != 240:
            assert output.read_asset(M, i) == rom.read_asset(M, i)
