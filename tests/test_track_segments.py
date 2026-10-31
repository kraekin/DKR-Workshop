"""Spatial compiler, source query bounds, seam planes and v10 integration."""
from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.exporter import export_obj
from src.core.level_model import LevelModel
from src.core.materials import MaterialEdit
from src.core.placement import TerrainSurface
from src.core.rom import AssetType,LUT_START,LUT_END,RomImage,parse_asset_lut
from src.core.track_import import ImportOptions,parse_obj,default_materials,validate_compiled_track
from src.core.track_segments import (MAX_CELL_FACES,QUERY_MARGIN,compile_segmented_obj,
    collision_helper_faces,collision_query,import_project_version,validate_segmented_track,
    _owned_counts,_grid_parameters,_links)
from src.core.track_rebuild import runtime_track
from src.core.geometry import geometry_profile


def road_obj(nx: int = 10,nz: int = 40) -> str:
    rows=['usemtl slot_6','vt 0 0','vt 1 0','vt 1 1','vt 0 1']
    for z in range(nz+1):
        for x in range(nx+1):
            rows.append(f'v {-2300+x*1200/nx} {24+round(40*np.sin(z/nz*np.pi))} {-11000+z*8000/nz}')
    for z in range(nz):
        for x in range(nx):
            a=z*(nx+1)+x+1;b=a+1;c=b+nx+1;d=a+nx+1
            # Reversed longitudinal direction to give +Y normals.
            rows.extend((f'f {a}/1 {d}/2 {c}/3',f'f {a}/1 {c}/3 {b}/4'))
    return '\n'.join(rows)


@pytest.fixture(scope='module')
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob('*.z64')))


@pytest.fixture(scope='module')
def source(rom: RomImage) -> EditSession:
    return EditSession(rom)


@pytest.fixture(scope='module')
def result(source: EditSession):
    mesh=parse_obj(road_obj(),max_faces=6000)
    return compile_segmented_obj(mesh,source.original_asset(AssetType.LEVEL_MODELS,5),source.material_references,
                                 default_materials(mesh,source.track_model(5)),ImportOptions(scale=1.0))


def validate(s: EditSession,raw: bytes) -> LevelModel:
    return validate_segmented_track(s.original_asset(AssetType.LEVEL_MODELS,5),raw,s.material_references,s.minimap_references)


def test_large_obj_opt_in_retains_old_single_segment_limit() -> None:
    with pytest.raises(ValueError,match='499'):parse_obj(road_obj())
    assert len(parse_obj(road_obj(),max_faces=6000).faces)==800


def test_spatial_layout_bsp_visibility_and_canonical_validation(source: EditSession,result) -> None:
    model=validate(source,result.raw)
    size,origin,cells=_grid_parameters(model)
    assert model.triangle_count>800 and len(model.segments)>1
    assert size==result.cell_size and len(model.bsp_nodes)==len(cells)-1
    assert all(1<=n<=MAX_CELL_FACES for n in _owned_counts(model))
    assert result.rendered_faces==sum(_owned_counts(model)) and result.seam_edges>0
    assert result.runtime_bytes<0x82a00 and result.packed_bytes%16==0
    assert import_project_version(source.original_asset(AssetType.LEVEL_MODELS,5),result.raw,source.material_references,source.minimap_references)==10
    p=struct.unpack_from('>I',result.raw,0x10)[0];width=(len(cells)+7)//8
    for i in range(len(cells)):
        assert int.from_bytes(result.raw[p+i*width:p+(i+1)*width],'little')==(1<<len(cells))-1
    # Source BSP traversal reaches each leaf once, in the expected near/far order.
    def order(index: int,low: int,high: int,point: tuple[int,int,int]) -> list[int]:
        n=model.bsp_nodes[index]
        left=order(n.left_node,low,n.segment_index-1,point) if n.left_node>=0 else [low]
        right=order(n.right_node,n.segment_index,high,point) if n.right_node>=0 else [high]
        return left+right if point[n.split_type]<n.split_value else right+left
    for point in ((-30000,0,-30000),(30000,0,30000),(-1700,24,-7000)):
        assert sorted(order(0,0,len(cells)-1,point))==list(range(len(cells)))


def test_seam_helpers_preserve_reciprocal_edge_planes(source: EditSession,result) -> None:
    model=validate(source,result.raw);rt=runtime_track(model);counts=_owned_counts(model)
    points=np.concatenate([s.vertices[s.indices[:n]] for s,n in zip(model.segments,counts)])
    owners=np.concatenate([np.full(n,i) for i,n in enumerate(counts)])
    graph,_,_,seams=_links(points,owners)
    offsets=np.r_[0,np.cumsum(counts)]
    checked=0
    for face,row in enumerate(graph):
        a=int(owners[face]);local=face-int(offsets[a])
        for edge,other in enumerate(row[1:]):
            b=int(owners[other])
            if other<=face or a==b:continue
            neighbor=int(other)-int(offsets[b])
            reverse=next(e for e,j in enumerate(graph[other,1:]) if j==face)
            ia=int(rt.segments[a].facets[local,edge+1]);ib=int(rt.segments[b].facets[neighbor,reverse+1])
            pa=rt.segments[a].planes[ia&0x7fff]*(-1 if ia&0x8000 else 1)
            pb=rt.segments[b].planes[ib&0x7fff]*(-1 if ib&0x8000 else 1)
            np.testing.assert_allclose(pa,-pb,atol=.03,rtol=1e-4)
            checked+=1
    assert checked==seams and checked>10


def test_local_query_certificate_and_floor_overlap(source: EditSession,result) -> None:
    model=validate(source,result.raw);rt=runtime_track(model)
    size,origin,cells=_grid_parameters(model)
    helpers=collision_helper_faces(model)
    rng=np.random.default_rng(23)
    # Boundaries are included, with negative coordinates and both directions.
    anchors=[(origin[0]+x*size+d,origin[1]+z*size+e) for x,z in cells for d,e in ((-27,-27),(0,0),(size-1,size-1))]
    anchors+=list(rng.uniform((-3500,-12000),(0,-2000),size=(80,2)))
    for x,z in anchors:
        a=np.array([[x,24,z]]);b=a+np.array([[size-QUERY_MARGIN,0,size-QUERY_MARGIN]])
        q=collision_query(model,a,b,runtime=rt)
        assert q.complete and len(q.matching_segments)<=4 and q.required_entries<=484
        assert not helpers.intersection(q.candidates)
        count=sum(s.bounds.minimum[0]-4<x<s.bounds.maximum[0]+4 and s.bounds.minimum[2]-4<z<s.bounds.maximum[2]+4 for s in model.segments)
        assert count<=4
    full=collision_query(model,np.array([[-3000,0,-12000]]),np.array([[0,0,-2000]]),runtime=rt)
    assert not full.complete
    assert len(full.matching_segments)>10 or full.required_entries>=500


def test_imported_floor_is_continuous_at_grid_seams(source: EditSession,result) -> None:
    model=validate(source,result.raw);terrain=TerrainSurface.from_model(model)
    for z in np.linspace(-10990,-3010,150):
        assert terrain.surface_y((-1700,500,int(z)),drop=True) is not None
    helpers=collision_helper_faces(model)
    assert len(helpers)==model.triangle_count-result.rendered_faces>0
    assert len(terrain.triangles)==result.rendered_faces


@pytest.mark.parametrize('field',['pvs','bsp','box','row','helper_flags','facets','metadata'])
def test_segmented_canonical_tamper_refused(source: EditSession,result,field: str) -> None:
    raw=bytearray(result.raw)
    sp=struct.unpack_from('>I',raw,4)[0]
    helpers=collision_helper_faces(LevelModel.from_bytes(result.raw))
    segment,face=min(helpers)
    s=LevelModel.from_bytes(raw).segments[segment]
    helper=next(i for i,b in enumerate(s.batches) if b.faces_offset==face)
    bp=struct.unpack_from('>I',raw,sp+segment*0x44+12)[0]
    fp=struct.unpack_from('>I',raw,sp+20)[0]
    offset={'pvs':struct.unpack_from('>I',raw,0x10)[0],
            'bsp':struct.unpack_from('>I',raw,0x14)[0]+7,
            'box':struct.unpack_from('>I',raw,8)[0]+7,
            'row':sp+0x29,'helper_flags':bp+helper*12+10,
            'facets':fp+1,'metadata':0x26}[field]
    raw[offset]^=1
    with pytest.raises(ValueError):validate(source,bytes(raw))


def test_v10_project_history_and_old_v9_permissions(rom: RomImage,result,tmp_path: Path) -> None:
    s=EditSession(rom);original=s.track_model(5).raw_data
    s.import_track(5,result.raw)
    path=tmp_path/'large.dkrproj';s.save_project(path,5)
    doc=json.loads(path.read_text());assert doc['version']==10
    loaded=EditSession.load_project(path)
    assert loaded.track_model(5).raw_data==result.raw and not loaded.dirty
    loaded.edit_minimap(5,{'red':123})
    loaded.revert_minimap(5)
    assert loaded.track_model(5).raw_data==result.raw
    s.undo();assert s.track_model(5).raw_data==original and not s.imported_track(5)
    s.redo();s.restore_stock_track(5);s.undo()
    assert s.track_model(5).raw_data==result.raw
    doc['version']=9;path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):EditSession.load_project(path)


def test_helper_flag_and_surface_edits_are_refused_atomically(rom: RomImage,result) -> None:
    s=EditSession(rom);s.import_track(5,result.raw)
    model=s.track_model(5);counts=_owned_counts(model)
    segment=next(i for i,c in enumerate(counts) if c<model.segments[i].triangle_count)
    batch=next(i for i,b in enumerate(model.segments[segment].batches) if b.faces_offset==counts[segment])
    signature,cursor=s._signature(),s._cursor
    with pytest.raises(ValueError,match='helper'):
        s.edit_track_materials(5,(MaterialEdit('flags',(segment,batch),0),))
    assert (s._signature(),s._cursor)==(signature,cursor)


def test_per_material_surface_choices_duplicate_shared_image_slots(source: EditSession) -> None:
    text=road_obj(1,1).replace('usemtl slot_6','usemtl road').replace('f 1/1','usemtl grass\nf 1/1',1)
    # Both faces use the same image, but have independent driving surfaces.
    text=text.replace('f 1/1 4/3 2/4','usemtl road\nf 1/1 4/3 2/4')
    mesh=parse_obj(text)
    if len(mesh.materials)==1:
        mesh=parse_obj('v -2000 24 -8000\nv -2000 24 -7000\nv -1000 24 -7000\nv -1000 24 -8000\nusemtl road\nf 1 2 3\nusemtl grass\nf 1 3 4')
    r=compile_segmented_obj(mesh,source.original_asset(AssetType.LEVEL_MODELS,5),source.material_references,
                            {'road':6,'grass':6},ImportOptions(scale=1.0),surfaces={'road':0,'grass':1})
    model=validate(source,r.raw)
    original=source.track_model(5)
    assert model.textures[:len(original.textures)]==original.textures
    assert len(model.textures)>len(original.textures)
    assert {t.surface_type for t in model.textures if t.texture_id==original.textures[6].texture_id}>={0,1}


def test_density_input_and_coordinate_limits_refuse(source: EditSession) -> None:
    dense=road_obj(25,25)
    mesh=parse_obj(dense,max_faces=6000)
    from src.core.track_import import ImportOptions
    with pytest.raises(ValueError,match='local collision'):
        compile_segmented_obj(mesh,source.original_asset(AssetType.LEVEL_MODELS,5),source.material_references,
            {'slot_6':6},ImportOptions(.1))
    with pytest.raises(ValueError,match='cell size'):
        compile_segmented_obj(mesh,source.original_asset(AssetType.LEVEL_MODELS,5),source.material_references,{'slot_6':6},ImportOptions(scale=1.0),cell_size=1)


def test_sharp_edge_exactly_on_a_cell_cut_uses_seam_guides(source: EditSession) -> None:
    mesh=parse_obj('v 0 0 0\nv 0 0 1000\nv 1022 0 1000\nv 1022 0 0\nv 1022 200 0\nv 1022 200 1000\nf 1 2 3\nf 1 3 4\nf 4 3 6\nf 4 6 5')
    r=compile_segmented_obj(mesh,source.original_asset(AssetType.LEVEL_MODELS,5),source.material_references,
        {'(default)':6},ImportOptions(scale=1.0),cell_size=1024)
    m=validate(source,r.raw)
    assert len(m.segments)>1 and r.seam_edges>0 and collision_helper_faces(m)


def test_interior_geometry_edit_and_protected_seam_vertices(rom: RomImage,result) -> None:
    s=EditSession(rom);s.import_track(5,result.raw)
    profile=geometry_profile(result.raw)
    assert profile.locked
    protected=next(iter(profile.locked))
    with pytest.raises(ValueError,match='seam guide'):
        s.edit_track_geometry(5,(protected,),(0,1,0))
    key=next((part.index,i) for part in s.track_model(5).segments for i in range(part.vertex_count)
             if (part.index,i) not in profile.locked)
    before=s.track_model(5).raw_data
    s.edit_track_geometry(5,(key,),(0,1,0))
    assert s.track_model(5).raw_data!=before
    s.undo();assert s.track_model(5).raw_data==before


@pytest.mark.parametrize('index',range(55))
def test_segmented_layout_on_every_original_template(source: EditSession,index: int) -> None:
    original=source.track_model(index)
    slot=next(i for i,t in enumerate(original.textures) if 0<=t.surface_type<=18)
    mesh=parse_obj('v -2000 24 -8000\nv -2000 24 -7000\nv -1000 24 -7000\nf 1 2 3')
    r=compile_segmented_obj(mesh,original.raw_data,source.material_references,{'(default)':slot},ImportOptions(scale=1.0))
    validate_segmented_track(original.raw_data,r.raw,source.material_references,source.minimap_references)


def test_in_memory_rom_and_obj_export_omit_helpers_and_preserve_assets(rom: RomImage,result,tmp_path: Path) -> None:
    s=EditSession(rom);s.import_track(5,result.raw)
    output=s.build_rom()
    edited=RomImage(output,'z64',parse_asset_lut(output,LUT_START,LUT_END))
    assert edited.read_asset(AssetType.LEVEL_MODELS,5,decompress=True)==result.raw
    assert all(rom.read_asset(AssetType.LEVEL_MODELS,i)==edited.read_asset(AssetType.LEVEL_MODELS,i) for i in range(55) if i!=5)
    assert all(rom.data[a.start:a.end]==output[b.start:b.end] for i,(a,b) in enumerate(zip(rom.sections,edited.sections)) if i not in (26,27))
    path=tmp_path/'large.obj';export=export_obj(s.track_model(5),path)
    mesh=parse_obj(path.read_text(),max_faces=6000)
    assert export.triangle_count==len(mesh.faces)==result.rendered_faces
    # Reimport exported geometry without duplicate hidden seam-guide faces.
    rebuilt=compile_segmented_obj(mesh,s.original_asset(AssetType.LEVEL_MODELS,5),s.material_references,
                                 default_materials(mesh,s.track_model(5)))
    assert rebuilt.rendered_faces>=result.rendered_faces
