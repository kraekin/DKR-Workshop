"""Small-track compiler, generated collision and atomic v9 project integration."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import pytest

from src.core.editing import EditSession, n64_checksums
from src.core.exporter import export_obj
from src.core.geometry import TRACK_HEAP, geometry_profile
from src.core.level_model import LevelModel
from src.core.materials import MaterialEdit
from src.core.rom import AssetType, LUT_START, LUT_END, RomImage, parse_asset_lut
from src.core.track_import import (ImportOptions, MAX_OBJ_BYTES, compile_obj,
    parse_obj, read_obj, default_materials, validate_compiled_track, collision_facets)
from src.core.track_rebuild import runtime_track

QUAD = '''v -5500 150 -11000
v -5500 150 -10000
v -4500 150 -10000
v -4500 150 -11000
vt 0 0
vt 0 1
vt 1 1
vt 1 0
usemtl slot_0
f 1/1 2/2 3/3 4/4
'''


@pytest.fixture(scope='module')
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob('*.z64')))


@pytest.fixture(scope='module')
def source(rom: RomImage) -> EditSession:
    return EditSession(rom)


def compiled(session: EditSession, text: str = QUAD, **kwargs: object):
    # These topology/collision fixtures are authored directly in game units.
    kwargs.setdefault('options', ImportOptions(scale=1.0))
    mesh = parse_obj(text)
    return compile_obj(mesh, session.original_asset(AssetType.LEVEL_MODELS,5),
                       session.material_references, default_materials(mesh,session.track_model(5)), **kwargs)


def validate(session: EditSession, raw: bytes) -> LevelModel:
    return validate_compiled_track(session.original_asset(AssetType.LEVEL_MODELS,5),raw,
                                   session.material_references,session.minimap_references)


def test_obj_indices_colors_normals_and_convex_polygon() -> None:
    text = QUAD.replace('v -5500 150 -11000','v -5500 150 -11000 .25 .5 .75 .8')
    text = text.replace('usemtl slot_0','vn 0 1 0\nusemtl two words')
    text = text.replace('f 1/1 2/2 3/3 4/4','f -4/-4/1 -3/-3/1 -2/-2/1 -1/-1/1')
    mesh = parse_obj(text)
    assert len(mesh.faces)==2 and mesh.materials==('two words',)
    assert mesh.colors[0]==(.25,.5,.75,.8)
    assert [c.vertex for c in mesh.faces[1].corners]==[0,2,3]
    assert parse_obj(QUAD.replace('v -5500 150 -11000','v -11000 300 -22000 2')).vertices[0]==mesh.vertices[0]


@pytest.mark.parametrize('text', [
    '', QUAD.replace('f 1/1 2/2 3/3 4/4','f 0 2 3'),
    QUAD.replace('f 1/1 2/2 3/3 4/4','f 1/99 2 3'),
    QUAD.replace('f 1/1 2/2 3/3 4/4','f 1//1 2 3'),
    QUAD.replace('f 1/1 2/2 3/3 4/4','f 1/1/1/1 2 3'),
    QUAD.replace('v -5500 150 -11000','v nan 150 0'),
    QUAD.replace('v -5500 150 -11000','v 0 0 0 0'),
    QUAD.replace('v -5500 150 -11000','v 0 0 0 2 0 0'),
    QUAD.replace('v -4500 150 -11000','v -4500 151 -11000'),
    QUAD.replace('f 1/1 2/2 3/3 4/4','f 1 1 2'),
    QUAD+'curv 1 2 3', QUAD+'usemtl', '#'* (MAX_OBJ_BYTES+1),
], ids=lambda text: f'input-{len(text)}-{text[:12].strip()}')
def test_obj_rejects_unsupported_or_malformed_input(text: str) -> None:
    with pytest.raises(ValueError):
        parse_obj(text)


def test_concave_polygon_requires_external_triangulation() -> None:
    with pytest.raises(ValueError,match='concave'):
        parse_obj('v 0 0 0\nv 0 0 4\nv 4 0 4\nv 2 0 2\nv 4 0 0\nf 1 2 3 4 5')


def test_bounded_utf8_file_reader(tmp_path: Path) -> None:
    path = tmp_path/'mesh.obj'
    path.write_bytes(b'\xef\xbb\xbf'+QUAD.encode())
    assert read_obj(path)==parse_obj(QUAD)
    path.write_bytes(b'\xff')
    with pytest.raises(ValueError,match='UTF-8'):read_obj(path)
    path.write_bytes(b' '*(MAX_OBJ_BYTES+1))
    with pytest.raises(ValueError,match='MiB'):read_obj(path)


def test_compile_generates_layout_uvs_bounds_facets_and_both_runtime_branches(source: EditSession) -> None:
    result = compiled(source)
    model = validate(source,result.raw)
    segment = model.segments[0]
    assert (result.faces,result.vertices,result.batches,result.shared_edges,result.boundary_edges)==(2,4,1,1,4)
    assert not model.bsp_nodes and result.runtime_bytes<TRACK_HEAP
    assert result.packed_bytes%16==0
    pvs = struct.unpack_from('>I',result.raw,0x10)[0]
    assert result.raw[pvs]==1
    assert model.textures==source.track_model(5).textures
    assert model.stored_bounds.minimum[1]<=-850 and model.stored_bounds.maximum[1]>=1150
    assert geometry_profile(result.raw).locked=={}
    info = model.textures[0]
    h = source.material_references[info.texture_id].header
    assert segment.uvs[0].tolist()==[[0,h.height*32],[0,0],[h.width*32,0]]
    runtime = runtime_track(model)
    assert runtime.byte_size==result.runtime_bytes
    assert len(runtime.segments[0].planes)==7 #2base +4boundary +1shared
    assert len(runtime_track(model,cutscene=True).segments[0].planes)==2
    assert all(mask for mask in runtime.segments[0].grid_masks)
    # Execute the source's plane-side containment convention at each centroid.
    planes,facets = runtime.segments[0].planes,runtime.segments[0].facets
    for face, points in enumerate(segment.vertices[segment.indices]):
        center = points.mean(axis=0)
        assert abs(planes[face,:3]@center+planes[face,3])<1e-3
        assert planes[face,1]>.99
        for value in facets[face,1:]:
            plane = planes[int(value)&0x7fff]
            distance = (plane[:3]@center+plane[3])*(-1 if value&0x8000 else 1)
            assert distance<0
    # The seam uses one shared plane with reciprocal inversion.
    assert sum(bool(v&0x8000) for v in facets[:,1:].flat)==1


def test_reverse_winding_transform_missing_uv_and_double_sided(source: EditSession) -> None:
    text = '\n'.join(line for line in QUAD.splitlines() if not line.startswith('vt'))
    text = text.replace('f 1/1 2/2 3/3 4/4','f 1 2 3 4')
    result = compiled(source,text,options=ImportOptions(.5,(0,20,0),True,True))
    model = validate(source,result.raw)
    assert model.bounds.minimum==(-2750.,95.,-5500.)
    assert (model.segments[0].triangle_flags==0x40).all()
    assert (runtime_track(model).segments[0].planes[:2,1]<-.99).all()


@pytest.mark.parametrize('option', [ImportOptions(0),ImportOptions(float('nan')),ImportOptions(100),ImportOptions(offset=(40000,0,0))])
def test_invalid_transforms_rejected(source: EditSession, option: ImportOptions) -> None:
    with pytest.raises(ValueError):compiled(source,options=option)


@pytest.mark.parametrize('text', [
    QUAD.replace('f 1/1 2/2 3/3 4/4','f 1 2 3\nf 3 2 1'),
    QUAD.replace('f 1/1 2/2 3/3 4/4','f 1 2 3\nf 1 4 3'),
    QUAD.replace('vt 1 0','vt 1000 0'),
    QUAD.replace('v -4500 150 -10000','v -5500.1 150 -10000'),
])
def test_invalid_quantized_topology_and_uvs_refused(source: EditSession,text: str) -> None:
    with pytest.raises(ValueError):compiled(source,text)


def test_nonmanifold_collision_edges_refused() -> None:
    points = np.array([[[0,0,0],[0,0,10],[10,0,0]],
                       [[0,0,10],[0,0,0],[-10,0,0]],
                       [[0,0,0],[0,0,10],[0,10,0]]])
    with pytest.raises(ValueError,match='Nonmanifold'):collision_facets(points)


@pytest.mark.parametrize('text',[
    # Two slopes sharing an edge, with each triangle independently triangulated.
    'v 0 0 0\nv 0 0 100\nv 100 40 100\nv 100 0 0\nf 1 2 3\nf 1 3 4',
    # A closed tetrahedron exercises every edge and nonhorizontal planes.
    'v 0 0 0\nv 100 0 0\nv 0 0 100\nv 0 100 0\nf 1 2 3\nf 1 4 2\nf 2 4 3\nf 3 4 1',
])
def test_slopes_and_closed_mesh_have_finite_unit_collision_planes(source: EditSession,text: str) -> None:
    model = validate(source,compiled(source,text).raw)
    rt = runtime_track(model).segments[0]
    np.testing.assert_allclose(np.linalg.norm(rt.planes[:,:3],axis=1),1,atol=1e-6)
    assert np.isfinite(rt.planes).all()
    for face,points in enumerate(model.segments[0].vertices[model.segments[0].indices]):
        assert abs(rt.planes[face,:3]@points.mean(axis=0)+rt.planes[face,3])<1e-4


@pytest.mark.parametrize('index',range(55))
def test_compile_for_each_original_target_and_keep_shared_texture_slots(source: EditSession,index: int) -> None:
    base = source.original_asset(AssetType.LEVEL_MODELS,index)
    mesh = parse_obj(QUAD)
    model = LevelModel.from_bytes(base)
    result = compile_obj(mesh,base,source.material_references,default_materials(mesh,model),ImportOptions(scale=1.0))
    imported = validate_compiled_track(base,result.raw,source.material_references,source.minimap_references)
    assert imported.textures==model.textures and imported.triangle_count==2


def test_compile_retains_current_appearance_and_refuses_wrong_slot_count(rom: RomImage) -> None:
    s = EditSession(rom)
    s.edit_minimap(5,{'red':123})
    s.edit_track_materials(5,(MaterialEdit('surface',(0,),2),))
    result = compiled(s,appearance=s.track_model(5).raw_data)
    model = validate(s,result.raw)
    assert model.textures[0].surface_type==2 and result.raw[0x39]==123
    other = next(s.track_model(i).raw_data for i in range(55) if len(s.track_model(i).textures)!=len(model.textures))
    with pytest.raises(ValueError,match='slot count'):compiled(s,appearance=other)


def islands(count: int) -> str:
    rows = []
    for i in range(count):
        x,z = i%25*100, i//25*100
        rows.extend((f'v {x} 0 {z}',f'v {x} 0 {z+50}',f'v {x+50} 0 {z}',f'f {3*i+1} {3*i+2} {3*i+3}'))
    return '\n'.join(rows)


def test_collision_candidate_limit_and_microcode_batch_splits(source: EditSession) -> None:
    result = compiled(source,islands(499))
    model = validate(source,result.raw)
    assert model.triangle_count==499 and result.batches>30
    s = model.segments[0]
    for b,end in zip(s.batches,(*s.batches[1:],s.terminal_batch)):
        assert 1<=end.vertices_offset-b.vertices_offset<=32
        assert 1<=end.faces_offset-b.faces_offset<=16
    with pytest.raises(ValueError,match='499'):parse_obj(islands(500))


@pytest.mark.parametrize('target', ['header','pvs','bounds','facets','runtime','flags','sentinel','padding'])
def test_canonical_baseline_rejects_tampered_generated_or_protected_data(source: EditSession,target: str) -> None:
    raw = bytearray(compiled(source).raw)
    seg,box,pvs = (struct.unpack_from('>I',raw,o)[0] for o in (4,8,0x10))
    batch = struct.unpack_from('>I',raw,seg+12)[0]
    facet = struct.unpack_from('>I',raw,seg+20)[0]
    offset = dict(header=0x26,pvs=pvs,bounds=box,facets=facet+3,runtime=seg+0x2b,
                  flags=batch+11,sentinel=batch+12,padding=0x4c)[target]
    raw[offset]^=1
    with pytest.raises(ValueError):validate(source,bytes(raw))


def test_multiple_materials_split_seams_sort_render_passes_and_map_defaults(source: EditSession) -> None:
    model = source.track_model(5)
    opaque = next(i for i,t in enumerate(model.textures) if not source.material_references[t.texture_id].translucent)
    trans = next(i for i,t in enumerate(model.textures) if source.material_references[t.texture_id].translucent)
    text = QUAD.replace('f 1/1 2/2 3/3 4/4',f'f 1/1 2/2 3/3\nusemtl slot_{trans}\nf 1/1 3/3 4/4').replace('usemtl slot_0',f'usemtl slot_{opaque}')
    result = compiled(source,text)
    s = validate(source,result.raw).segments[0]
    assert result.vertices==6 and result.shared_edges==1 and s.opaque_batch_count==1
    assert [b.texture_index for b in s.batches]==[opaque,trans]
    text = QUAD.replace('slot_0',f'texture_{model.textures[opaque].texture_id}_frame_0')
    assert default_materials(parse_obj(text),model)[parse_obj(text).materials[0]]==opaque


def test_import_undo_redo_reimport_restore_and_saved_signatures(rom: RomImage) -> None:
    s = EditSession(rom)
    original = s.track_model(5).raw_data
    first = compiled(s).raw
    s.import_track(5,first)
    assert s.dirty and s.undo_label=='Import custom track' and s.imported_track(5)
    signature,cursor = s._signature(),s._cursor
    assert not s.import_track(5,first) and s._cursor==cursor
    assert s.preview_track_import(5,first).can_export and s._signature()==signature
    second = compiled(s,options=ImportOptions(scale=1.0,offset=(0,50,0))).raw
    s.import_track(5,second)
    s.undo()
    assert s.track_base(5)==first
    s.undo()
    assert not s.imported_track(5) and s.track_model(5).raw_data==original and not s.dirty
    s.redo();s.redo()
    assert s.track_base(5)==second
    s.restore_stock_track(5)
    assert not s.imported_track(5) and not s.dirty
    s.undo()
    assert s.track_base(5)==second
    s.redo()
    assert s.track_model(5).raw_data==original


def test_import_coexists_with_geometry_material_minimap_and_v9_reopen(rom: RomImage,tmp_path: Path) -> None:
    s = EditSession(rom)
    s.import_track(5,compiled(s).raw)
    baseline = s.track_base(5)
    s.edit_track_geometry(5,((0,0),),(0,8,0))
    s.edit_track_materials(5,(MaterialEdit('color',(0,0),(200,100,50,255)),))
    s.edit_minimap(5,{'red':123})
    raw = s.track_model(5).raw_data
    path = tmp_path/'import.dkrproj'
    s.save_project(path,5)
    doc = json.loads(path.read_text())
    assert doc['version']==9 and len(doc['track_imports'])==1 and not doc['asset_edits']
    loaded = EditSession.load_project(path)
    assert not loaded.dirty and loaded.track_base(5)==baseline and loaded.track_model(5).raw_data==raw
    assert loaded.export_report().can_export
    loaded.revert_track_geometry(5)
    assert loaded.track_model(5).segments[0].vertices[0,1]==150
    assert loaded.track_model(5).segments[0].colors[0].tolist()==[200,100,50,255]
    loaded.revert_track_materials(5);loaded.revert_minimap(5)
    assert loaded.track_model(5).raw_data==baseline
    loaded.restore_stock_track(5)
    assert loaded.project_document()['version']==6


@pytest.mark.parametrize('kind',['baseline','current','hash','duplicate','version','too_large'])
def test_v9_rejects_tampering_without_mutating_session(rom: RomImage,tmp_path: Path,kind: str) -> None:
    s = EditSession(rom)
    s.import_track(5,compiled(s).raw)
    doc = s.project_document()
    row = doc['track_imports'][0]
    if kind in ('baseline','current'):
        data = bytearray.fromhex(row[kind]); data[0x26]^=1; row[kind]=data.hex()
    elif kind=='hash':row['base_asset_sha1']='bad'
    elif kind=='duplicate':doc['track_imports'].append(dict(row))
    elif kind=='version':doc['version']=8
    else:row['baseline']='00'*(TRACK_HEAP+1)
    path = tmp_path/'bad.dkrproj';path.write_text(json.dumps(doc))
    signature = s._signature()
    with pytest.raises(ValueError):EditSession.load_project(path)
    assert s._signature()==signature


def test_failed_import_and_rom_budget_refusal_leave_all_project_state(rom: RomImage,monkeypatch) -> None:
    import src.core.editing as editing
    s = EditSession(rom)
    raw = compiled(s).raw
    s.import_track(5,raw);s.undo()
    signature,cursor,history = s._signature(),s._cursor,tuple(s._history)
    with pytest.raises(ValueError):s.import_track(5,raw[:-16])
    original_report = editing.make_export_report
    monkeypatch.setattr(editing,'make_export_report',lambda *a,**k: replace(original_report(*a,**k),errors=('test budget exhausted',)))
    with pytest.raises(ValueError,match='budget exhausted'):s.import_track(5,raw)
    assert s._signature()==signature and s._cursor==cursor and tuple(s._history)==history and s.can_redo


def test_in_memory_rom_and_obj_exports_preserve_unrelated_assets(rom: RomImage,tmp_path: Path) -> None:
    s = EditSession(rom)
    result = compiled(s)
    s.import_track(5,result.raw)
    report = s.export_report()
    output = s.build_rom()
    assert len(output)==len(rom.data) and report.can_export
    assert struct.unpack_from('>2I',output,0x10)==n64_checksums(output)
    edited = RomImage(output,'z64',parse_asset_lut(output,LUT_START,LUT_END))
    assert edited.read_asset(AssetType.LEVEL_MODELS,5,decompress=True)==result.raw
    assert all(rom.data[a.start:a.end]==output[b.start:b.end] for i,(a,b) in enumerate(zip(rom.sections,edited.sections)) if i not in (26,27))
    assert all(rom.read_asset(AssetType.LEVEL_MODELS,i)==edited.read_asset(AssetType.LEVEL_MODELS,i) for i in range(55) if i!=5)
    assert [(a.section,a.index) for a in report.assets]==[(27,5)]
    path = tmp_path/'import.obj'
    export_obj(s.track_model(5),path)
    mesh = read_obj(path)
    assert len(mesh.faces)==2 and len(mesh.vertices)==4
    assert hashlib.sha1(rom.source_path.read_bytes()).hexdigest()==hashlib.sha1(rom.data).hexdigest()
