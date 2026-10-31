"""Source-compatible vertex loads, including export of pre-fix project overlays."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.level_model import LevelModel
from src.core.model_editing import plan_models, structures
from src.core.object_models import ObjectLibrary, ObjectModel
from src.core.object_rebuild import compile_static, rebuild_obj
from src.core.render_batches import MAX_BATCH_VERTICES, rebatch_static_model, rebatch_track, split_batches
from src.core.rom import AssetType, LUT_END, LUT_START, RomImage, parse_asset_lut
from src.core.track_import import ImportOptions, compile_obj, default_materials, parse_obj, read_obj
from src.core.track_segments import compile_segmented_obj
from src.core.track_rebuild import runtime_track

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(ROOT.glob('*.z64'))
    if not paths:
        pytest.skip('Original local Rev1 ROM absent')
    return RomImage.from_file(paths[0])


def ranges(model: LevelModel) -> list[int]:
    return [end.vertices_offset-b.vertices_offset for s in model.segments
            for b, end in zip(s.batches, (*s.batches[1:], s.terminal_batch))]


def same_faces(before: LevelModel, after: LevelModel) -> None:
    assert before.textures == after.textures
    assert before.bsp_nodes == after.bsp_nodes
    assert before.stored_bounds == after.stored_bounds
    assert len(before.segments) == len(after.segments)
    for a, b in zip(before.segments, after.segments):
        assert a.bounds == b.bounds
        np.testing.assert_array_equal(a.vertices[a.indices], b.vertices[b.indices])
        np.testing.assert_array_equal(a.colors[a.indices], b.colors[b.indices])
        np.testing.assert_array_equal(a.uvs, b.uvs)
        np.testing.assert_array_equal(a.triangle_flags, b.triangle_flags)
        def materials(s):
            return [(batch.texture_index, batch.misc_data, batch.texture_offset, batch.flags,
                     batch.vertex_override == 0, i < s.opaque_batch_count)
                    for i, (batch, end) in enumerate(zip(s.batches, (*s.batches[1:], s.terminal_batch)))
                    for _ in range(batch.faces_offset, end.faces_offset)]
        assert materials(a) == materials(b)


def test_original_tracks_and_object_models_never_load_more_than_24_vertices(rom: RomImage) -> None:
    tracks = [LevelModel.from_bytes(rom.read_asset(AssetType.LEVEL_MODELS, i, decompress=True))
              for i in range(rom.count(AssetType.LEVEL_MODELS))]
    library = ObjectLibrary(rom)
    models = [library.model(i).mesh for i in range(rom.count(AssetType.OBJECT_MODELS))]
    assert len(tracks) == 55 and len(models) == 390
    for group in (tracks, models):
        sizes = [n for m in group for n in ranges(m)]
        assert max(sizes) == MAX_BATCH_VERTICES == 24


@pytest.mark.parametrize('override', [0, 32])
def test_split_retains_rows_colors_corner_data_unused_references_and_matrix_kind(override: int) -> None:
    vertices = tuple((i % 16, i % 3, 0, i, 100, 200, 255) for i in range(32))
    triangles = tuple((0x40, 3*i, 3*i+1, 3*i+2, -100, 200, -300, 400, -500, 600) for i in range(10))
    batches = ((2, override, 0, 0, 7, 4, 0x800), (255, 0, 32, 10, 255, 0, 0))
    result = split_batches(vertices, triangles, batches)
    assert result is not None
    assert len(result.batches) == 3
    assert len(result.triangles) == 10
    assert set(result.remap) == set(range(32))
    assert tuple(result.vertices[result.remap[i]] for i in range(32)) == vertices
    decoded = []
    for batch, end in zip(result.batches, result.batches[1:]):
        assert 1 <= end[2]-batch[2] <= 24
        assert batch[1] == (end[2]-batch[2] if override else 0)
        assert (batch[0], *batch[4:]) == (2, 7, 4, 0x800)
        for face in result.triangles[batch[3]:end[3]]:
            decoded.append((face[0], tuple(result.vertices[batch[2]+i] for i in face[1:4]), face[4:]))
    assert decoded == [(f[0], tuple(vertices[i] for i in f[1:4]), f[4:]) for f in triangles]
    assert split_batches(result.vertices, result.triangles, result.batches) is None


def test_split_preserves_distinct_equal_xyz_rows_and_boundary_duplicates() -> None:
    vertices = tuple((i % 8, 0, 0, i, 0, 0, 255) for i in range(32))
    faces = tuple((0, 0, i, i+1, 0, 0, 0, 0, 0, 0) for i in range(1, 31, 2))
    result = split_batches(vertices, faces, ((0, 0, 0, 0, 255, 0, 0), (0, 0, 32, 15, 255, 0, 0)))
    assert result is not None
    assert len(result.vertices) > len(vertices)  # shared row 0 duplicated across loads
    assert set(result.vertices) == set(vertices)


def test_split_refuses_mixed_matrix_ranges() -> None:
    with pytest.raises(ValueError, match='mixed-matrix'):
        split_batches(tuple((i, 0, 0, 255, 255, 255, 255) for i in range(32)),
                      ((0, 0, 1, 2, 0, 0, 0, 0, 0, 0),),
                      ((0, 1, 0, 0, 255, 0, 0), (0, 0, 32, 1, 255, 0, 0)))


@pytest.mark.parametrize('curved', [False, True])
def test_legacy_fe_rebatch_preserves_normals_or_refuses(curved):
    vertices = [(0, 0, 0, 255, 255, 255, 255)]
    for i in range(15):
        vertices.extend([(10+i, 0, 1, 255, 255, 255, 255),
                         (10+i, 1, 1, 255, 255, 255, 255) if curved else (10+i, 0, 2, 255, 255, 255, 255)])
    vertices.append((90, 90, 90, 255, 255, 255, 255))
    faces = tuple((0, 0, 2*i+1, 2*i+2, 0, 0, 0, 0, 0, 0) for i in range(15))
    batches = ((0, 0, 0, 0, 254, 0, 0), (255, 0, 32, 15, 255, 0, 0))
    if curved:
        with pytest.raises(ValueError, match='normals would change'):
            split_batches(tuple(vertices), faces, batches)
    else:
        result = split_batches(tuple(vertices), faces, batches)
        assert result is not None and len(result.vertices) > len(vertices)


def disjoint_mesh() -> str:
    rows = []
    for i in range(20):
        x, z = -5500+(i % 5)*100, -11000+(i//5)*100
        rows += [f'v {x} 150 {z}', f'v {x} 150 {z+30}', f'v {x+30} 150 {z}',
                 f'f {i*3+1} {i*3+2} {i*3+3}']
    return '\n'.join(rows)+'\n'


@pytest.mark.parametrize('segmented', [False, True])
def test_new_compiler_and_legacy_project_export_preserve_faces_collision_and_history(
        rom: RomImage, monkeypatch, tmp_path: Path, segmented: bool) -> None:
    import src.core.track_import as importer
    import src.core.track_segments as spatial
    session = EditSession(rom)
    base = session.original_asset(AssetType.LEVEL_MODELS, 5)
    mesh = parse_obj(disjoint_mesh())
    materials = default_materials(mesh, session.track_model(5))
    compiler = compile_segmented_obj if segmented else compile_obj
    current = compiler(mesh, base, session.material_references, materials, ImportOptions(scale=1.0)).raw
    assert max(ranges(LevelModel.from_bytes(current))) <= 24
    with monkeypatch.context() as patch:
        patch.setattr(importer, 'MAX_BATCH_VERTICES', 32)
        patch.setattr(spatial, 'MAX_BATCH_VERTICES', 32)
        legacy = compiler(mesh, base, session.material_references, materials, ImportOptions(scale=1.0)).raw
    assert max(ranges(LevelModel.from_bytes(legacy))) > 24
    fixed = rebatch_track(legacy, segmented=segmented)
    assert max(ranges(LevelModel.from_bytes(fixed))) <= 24
    same_faces(LevelModel.from_bytes(legacy), LevelModel.from_bytes(fixed))
    a, b = (runtime_track(LevelModel.from_bytes(raw)) for raw in (legacy, fixed))
    for old, new in zip(a.segments, b.segments):
        np.testing.assert_array_equal(old.facets, new.facets)
        np.testing.assert_array_equal(old.planes, new.planes)
        np.testing.assert_array_equal(old.grid_masks, new.grid_masks)
    assert rebatch_track(fixed, segmented=segmented) == fixed
    preview = session.preview_track_import(5, legacy)
    assert next(d for d in preview.assets if d.section == 27).edited_bytes == len(fixed)
    assert session.import_track(5, legacy)
    path = tmp_path/'legacy.dkrproj'
    session.save_project(path)
    loaded = EditSession.load_project(path, base_path=rom.source_path)
    signature = loaded._signature()
    before = loaded.current_asset(AssetType.LEVEL_MODELS, 5)
    data = loaded.build_rom()
    exported = RomImage(data, rom.byte_order, parse_asset_lut(data, LUT_START, LUT_END))
    assert exported.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True) == fixed
    assert loaded.current_asset(AssetType.LEVEL_MODELS, 5) == before == legacy
    assert loaded._signature() == signature
    assert loaded.export_report().can_export
    assert any('24 vertices' in detail for d in loaded.export_report().assets for detail in d.changes)
    for section in AssetType:
        if int(section) < len(rom.sections) and int(section) not in (26, 27):
            assert exported.section(section) == rom.section(section)
    session.undo()
    assert session.current_asset(AssetType.LEVEL_MODELS, 5) == base
    assert session.build_rom() == rom.data


def test_gentle_hills_spatial_batches_and_collision_helpers(rom: RomImage, monkeypatch) -> None:
    import src.core.track_import as importer
    import src.core.track_segments as spatial
    session = EditSession(rom)
    mesh = read_obj(ROOT/'artifacts/samples/blender-starter-tracks/03-gentle-hills/03-gentle-hills.obj')
    base = session.original_asset(AssetType.LEVEL_MODELS, 5)
    mapping = {name: slot for name, slot in zip(mesh.materials, (0, 1, 2))}
    with monkeypatch.context() as patch:
        patch.setattr(importer, 'MAX_BATCH_VERTICES', 32)
        patch.setattr(spatial, 'MAX_BATCH_VERTICES', 32)
        legacy = compile_segmented_obj(mesh, base, session.material_references, mapping, ImportOptions(scale=1.0)).raw
    fixed = rebatch_track(legacy, segmented=True)
    old, new = (LevelModel.from_bytes(raw) for raw in (legacy, fixed))
    assert len(old.segments) > 1 and max(ranges(old)) > 24
    assert max(ranges(new)) <= 24
    same_faces(old, new)
    for a, b in zip(runtime_track(old).segments, runtime_track(new).segments):
        np.testing.assert_array_equal(a.facets, b.facets)
        np.testing.assert_array_equal(a.planes, b.planes)
    assert session.import_track(5, legacy)
    assert session.export_report().can_export


def test_static_legacy_export_preserves_attachment_and_collision_references(rom: RomImage, monkeypatch) -> None:
    import src.core.object_rebuild as compiler
    index = 83
    original = rom.read_asset(AssetType.OBJECT_MODELS, index, decompress=True)
    text = rebuild_obj(original, rom)
    start = sum(line.startswith('v ') for line in text.splitlines())
    text += '\nusemtl batch_0\n'
    for i in range(20):
        x, y = (i % 5)*10, (i//5)*10
        vi = start+i*3+1
        text += f'v {x/100} {y/100} 0\nv {(x+5)/100} {y/100} 0\nv {x/100} {(y+5)/100} 0\nf {vi} {vi+1} {vi+2}\n'
    assert max(ranges(ObjectModel.from_bytes(compile_static(rom, index, text).raw).mesh)) <= 24
    with monkeypatch.context() as patch:
        patch.setattr(compiler, 'MAX_BATCH_VERTICES', 32)
        legacy = compile_static(rom, index, text).raw
    assert max(ranges(ObjectModel.from_bytes(legacy).mesh)) > 24
    fixed = rebatch_static_model(rom, index, original, legacy)
    before, after = (ObjectModel.from_bytes(raw).mesh for raw in (legacy, fixed))
    # Object mesh bounds expand around the same geometry, independent of array order.
    same_faces(before, after)
    assert max(ranges(after)) <= 24
    for old_ids, new_ids in zip(structures(legacy), structures(fixed)):
        assert len(old_ids) == len(new_ids)
        for a, b in zip(old_ids, new_ids):
            old_row, new_row = (a[0], b[0]) if isinstance(a, tuple) else (a, b)
            np.testing.assert_array_equal(before.segments[0].vertices[old_row], after.segments[0].vertices[new_row])
    assert any(structures(legacy))
    assert rebatch_static_model(rom, index, original, fixed) == fixed
    session = EditSession(rom)
    plan = plan_models(session, {(AssetType.OBJECT_MODELS, index): legacy})
    assert session.apply_models(plan)
    signature = session._signature()
    data = session.build_rom()
    exported = RomImage(data, rom.byte_order, parse_asset_lut(data, LUT_START, LUT_END))
    assert exported.read_asset(AssetType.OBJECT_MODELS, index, decompress=True) == fixed
    assert session._signature() == signature
    assert session.current_asset(AssetType.OBJECT_MODELS, index) == legacy
    assert next(d for d in session.export_report().assets if d.section == int(AssetType.OBJECT_MODELS)).edited_bytes == len(fixed)

