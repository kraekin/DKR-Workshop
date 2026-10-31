"""sidecars, N64 artwork, appended tables and atomic v11 projects."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image
import pytest

from src.core.editing import EditSession
from src.core.rom import AssetType, RomImage, LUT_START, LUT_END, parse_asset_lut
from src.core.track_import import ImportOptions, parse_obj, default_materials
from src.core.track_segments import compile_segmented_obj
from src.core.track_artwork import (ObjMaterial, TextureOptions, MaterialImage, SIZES,
    build_texture, validate_custom_texture, default_options, read_png,
    read_obj_materials, stage_artwork, texture_pool_refs)
from src.core.textures import Texture, TextureFormat

OBJ = 'mtllib material.mtl\nusemtl Road\nv -2000 24 -7000\nv -2000 24 -6600\nv -1600 24 -6600\nvt 0 0\nvt 0 1\nvt 1 1\nf 1/1 2/2 3/3\n'


@pytest.fixture(scope='module')
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob('*.z64')))


def pixels() -> np.ndarray:
    result=np.zeros((16,32,4),np.uint8)
    result[:8,:,0]=255;result[8:,:,2]=255;result[:,:,3]=255
    return result


def compile_art(s: EditSession):
    mesh=parse_obj(OBJ)
    image=MaterialImage(ObjMaterial('Road'),pixels(),TextureOptions(32,16),1)
    appearance,mapping,added,refs=stage_artwork(s.track_model(5).raw_data,s.material_references,
        default_materials(mesh,s.track_model(5)),{'Road':image},
        {s.rom.count(AssetType.TEXTURES_3D)+i:raw for i,raw in enumerate(s.custom_textures)})
    result=compile_segmented_obj(mesh,s.original_asset(AssetType.LEVEL_MODELS,5),refs,mapping,ImportOptions(scale=1.0),appearance=appearance)
    return result,added


@pytest.mark.parametrize('fmt',[TextureFormat.RGBA16,TextureFormat.RGBA32])
@pytest.mark.parametrize('size',[8,16,32])
@pytest.mark.parametrize('alpha',['Opaque','Cutout','Blend'])
def test_n64_image_header_pixels_and_alpha(fmt,size,alpha):
    opt=TextureOptions(size,size,fmt,alpha,True,False)
    p=pixels();p[:4,:,3]=0;p[4:8,:,3]=64
    if alpha=='Blend' and fmt!=TextureFormat.RGBA32:
        with pytest.raises(ValueError,match='Blend'):build_texture(p,opt)
        return
    raw=build_texture(p,opt)
    h=validate_custom_texture(raw)
    assert (h.width,h.height,h.format,h.frame_count,h.compressed)==(size,size,fmt,1,False)
    assert h.clamp_u and not h.clamp_v and h.frame_size==len(raw) and len(raw)%16==0
    out=Texture.from_bytes(raw).frames[0].pixels
    assert out[0,0,0]==255 and out[-1,0,2]==255
    if alpha=='Opaque':assert np.all(out[:,:,3]==255)
    if alpha=='Cutout':assert set(np.unique(out[:,:,3]))=={0,255}
    if alpha=='Blend':assert 64 in out[:,:,3]


@pytest.mark.parametrize('opt',[TextureOptions(64,64),TextureOptions(64,32,TextureFormat.RGBA32),
    TextureOptions(7,8),TextureOptions(32,32,TextureFormat.CI4),TextureOptions(alpha='Wrong')])
def test_unsupported_tmem_and_shapes_rejected(opt):
    with pytest.raises(ValueError):build_texture(pixels(),opt)


def test_defaults_fit_tmem_and_preserve_opacity():
    p=np.full((128,256,4),128,np.uint8)
    opt=default_options(p,ObjMaterial('M'))
    assert opt.format==TextureFormat.RGBA32 and opt.width*opt.height*4<=4096
    validate_custom_texture(build_texture(p,opt))


@pytest.mark.parametrize('offset',[5,6,8,10,12,18,19,20,22,29,31])
def test_custom_header_tamper_rejected(offset):
    raw=bytearray(build_texture(pixels(),TextureOptions(32,16)))
    raw[offset]^=0x80
    with pytest.raises(ValueError):validate_custom_texture(bytes(raw))


@pytest.mark.parametrize('alpha_first',[False,True])
def test_png_mtl_paths_colors_and_opacity(tmp_path,alpha_first):
    folder=tmp_path/'art folder';folder.mkdir()
    png=folder/'paint road.png';Image.fromarray(pixels()).save(png)
    obj=tmp_path/'course.obj';obj.write_text(OBJ.replace('material.mtl','"my materials.mtl"'))
    maps=['map_Kd -clamp on "art folder\\paint road.png"','map_d -imfchan a "art folder/paint road.png"']
    (tmp_path/'my materials.mtl').write_text('newmtl Road\nKd 0.5 1 1\nd 0.5\n'+'\n'.join(reversed(maps) if alpha_first else maps)+'\n')
    material,warnings=read_obj_materials(obj)
    m=material['Road'];assert not m.problems and not warnings and m.image==png.resolve()
    p=read_png(m.image);raw=build_texture(p,default_options(p,m),diffuse=m.diffuse,opacity=m.opacity)
    out=Texture.from_bytes(raw).frames[0].pixels
    assert out[0,0,0]==128 and out[0,0,3]==128


def test_missing_and_unsupported_materials_are_explicit(tmp_path):
    obj=tmp_path/'course.obj';obj.write_text(OBJ)
    assert 'missing' in read_obj_materials(obj)[1][0]
    (tmp_path/'material.mtl').write_text('newmtl Road\nmap_Kd -s 2 2 2 road.png\nmap_d other.png\n')
    mats,_=read_obj_materials(obj)
    assert len(mats['Road'].problems)==2


@pytest.mark.parametrize('text',['newmtl A\nKd nan 1 1','newmtl A\nd 2','newmtl A\nTr -1',
    'newmtl A\nnewmtl A','newmtl A\nmap_Kd https://example.com/x.png'])
def test_invalid_sidecars_rejected(tmp_path,text):
    obj=tmp_path/'course.obj';obj.write_text(OBJ)
    (tmp_path/'material.mtl').write_text(text)
    with pytest.raises(ValueError):read_obj_materials(obj)


def test_dedicated_import_atomic_preview_history_and_stock_isolation(rom):
    s=EditSession(rom);signature=s._signature();old=s.current_asset(AssetType.LEVEL_MODELS,5)
    result,added=compile_art(s)
    count=rom.count(AssetType.TEXTURES_3D)
    report=s.preview_track_import(5,result.raw,textures=added)
    assert report.can_export and not s.dirty and s._signature()==signature and s.custom_textures==()
    assert any(d.section==2 and d.index==count and '5: Ancient Lake' in d.levels for d in report.assets)
    s.import_track(5,result.raw,textures=added)
    assert s.export_report().projected_end==report.projected_end
    assert s.asset_source.count(AssetType.TEXTURES_3D)==count+1 and s.project_document()['version']==11
    assert s.track_model(5).textures[-1].texture_id==count and s.track_model(5).textures[-1].surface_type==1
    s.undo();assert not s.custom_textures and not s.dirty and s.current_asset(AssetType.LEVEL_MODELS,5)==old
    s.redo();assert s.custom_textures==added and s.current_asset(AssetType.LEVEL_MODELS,5)==result.raw
    for i in (0,186,count-1):assert s.asset_source.read_asset(AssetType.TEXTURES_3D,i)==rom.read_asset(AssetType.TEXTURES_3D,i)


def test_identical_images_reuse_dedicated_ids(rom):
    s=EditSession(rom);result,added=compile_art(s);s.import_track(5,result.raw,textures=added)
    again,new=compile_art(s)
    assert not new and again.raw==result.raw


def test_v11_embedded_artwork_reopen_pixels_and_legacy_gate(rom,tmp_path):
    s=EditSession(rom);result,added=compile_art(s);s.import_track(5,result.raw,textures=added)
    i=rom.count(AssetType.TEXTURES_3D)
    p=s.image_texture(AssetType.TEXTURES_3D,i).frames[0].pixels.copy();p[:]=255
    s.import_image(AssetType.TEXTURES_3D,i,0,p)
    path=tmp_path/'course.dkrproj';s.save_project(path,5)
    again=EditSession.load_project(path)
    assert again.custom_textures==added and again.current_asset(AssetType.TEXTURES_3D,i)==s.current_asset(AssetType.TEXTURES_3D,i)
    assert again.track_model(5).raw_data==result.raw and not again.dirty
    document=json.loads(path.read_text());document['version']=10;path.write_text(json.dumps(document))
    with pytest.raises(ValueError):EditSession.load_project(path)


def test_appended_texture_table_rom_reloads_and_preserves_stock(rom):
    s=EditSession(rom);result,added=compile_art(s);s.import_track(5,result.raw,textures=added)
    data=s.build_rom();out=RomImage(data,'z64',parse_asset_lut(data,LUT_START,LUT_END))
    assert len(data)==len(rom.data)
    count=rom.count(AssetType.TEXTURES_3D)
    assert out.count(AssetType.TEXTURES_3D)==count+1
    assert out.read_asset(AssetType.TEXTURES_3D,count)==added[0]
    assert Texture.from_bytes(out.read_asset(AssetType.TEXTURES_3D,count)).frames[0].pixels[0,0,0]==255
    for i in range(count):assert out.read_asset(AssetType.TEXTURES_3D,i)==rom.read_asset(AssetType.TEXTURES_3D,i)
    for section in range(len(rom.sections)):
        if section not in (2,3,26,27):assert out.section(section)==rom.section(section)


def test_failed_artwork_import_preserves_everything(rom):
    s=EditSession(rom);result,added=compile_art(s);signature=s._signature()
    broken=bytearray(added[0]);broken[29]=1
    with pytest.raises(ValueError):s.import_track(5,result.raw,textures=(bytes(broken),))
    assert not s.custom_textures and not s.can_undo and s._signature()==signature
    with pytest.raises(ValueError):texture_pool_refs(32768,added)


def test_budget_refusal_does_not_install_texture_pool(rom,monkeypatch):
    from src.core.export_report import make_export_report as original
    from src.core import editing
    s=EditSession(rom);result,added=compile_art(s);signature=s._signature()
    def refuse(*args,**kwargs):
        report=original(*args,**kwargs)
        return replace(report,errors=report.errors+('Capacity test refusal',))
    monkeypatch.setattr(editing,'make_export_report',refuse)
    with pytest.raises(ValueError,match='refusal'):s.import_track(5,result.raw,textures=added)
    assert s._signature()==signature and not s.custom_textures and not s.can_undo


def test_malformed_png_and_animated_png_refused(tmp_path):
    path=tmp_path/'bad.png';path.write_bytes(b'not a png')
    with pytest.raises((ValueError,OSError)):read_png(path)
    path=tmp_path/'animated.png'
    a=Image.fromarray(pixels());b=Image.fromarray(pixels()[:,::-1].copy())
    b.putpixel((0,0),(0,255,0,255))
    a.save(path,save_all=True,append_images=[b],duration=100,loop=0)
    with pytest.raises(ValueError,match='single-frame'):read_png(path)


@pytest.mark.parametrize('mutate',[
    lambda d:d['custom_textures'].append('00'),
    lambda d:d['custom_textures'].__setitem__(0,'gg'),
    lambda d:d.__setitem__('custom_textures',d['custom_textures']*129),
    lambda d:d['track_imports'][0].__setitem__('current','00'),
])
def test_project_custom_asset_tamper_refused(rom,tmp_path,mutate):
    s=EditSession(rom);result,added=compile_art(s);s.import_track(5,result.raw,textures=added)
    document=s.project_document();mutate(document)
    path=tmp_path/'bad.dkrproj';path.write_text(json.dumps(document))
    with pytest.raises(ValueError):EditSession.load_project(path)


def test_custom_obj_mtl_png_round_trip_keeps_pixels_and_uvs(rom,tmp_path):
    from src.core.exporter import export_obj
    from src.core.textures import load_model_textures,model_uvs
    from src.core.track_import import read_obj
    s=EditSession(rom);result,added=compile_art(s);s.import_track(5,result.raw,textures=added)
    model=s.track_model(5);textures=load_model_textures(s.asset_source,model)
    output=export_obj(model,tmp_path/'custom.obj',textures=textures)
    mesh=read_obj(output.path);materials,warnings=read_obj_materials(output.path)
    assert not warnings and len(materials)==2  # Export also defines untextured.
    m=materials[mesh.faces[0].material]
    png=read_png(m.image)
    index=rom.count(AssetType.TEXTURES_3D)
    assert np.array_equal(png,textures[index].frames[0].pixels)
    uv=model_uvs(model,textures,obj=True)
    assert np.allclose(np.array([mesh.uvs[c.uv] for c in mesh.faces[0].corners]),uv[0])


def test_dedicated_png_browser_orientation_matches_imported_artwork(rom):
    from src.core.image_assets import png_flip_default,png_rows
    s=EditSession(rom);result,added=compile_art(s);s.import_track(5,result.raw,textures=added)
    index=rom.count(AssetType.TEXTURES_3D)
    assert png_flip_default(s.asset_source,AssetType.TEXTURES_3D,186)
    assert not png_flip_default(s.asset_source,AssetType.TEXTURES_3D,index)
    p=s.image_texture(AssetType.TEXTURES_3D,index).frames[0].pixels
    assert np.array_equal(png_rows(p,flip_y=png_flip_default(s.asset_source,AssetType.TEXTURES_3D,index)),pixels())
