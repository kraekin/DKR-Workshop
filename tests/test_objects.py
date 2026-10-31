"""Object framing, ID translation, routes and picking, independent of Qt/GL."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import json
from pathlib import Path
import re
import struct

import numpy as np
import pytest

from src.core.level_header import LevelHeader, load_level_catalog
from src.core.objects import (
    BEHAVIOR_NAMES, ENTRY_LAYOUTS, ObjectDatabase, ObjectDefinition, ObjectError, ObjectMap,
    build_race_paths, catmull_rom, load_object_database, load_object_map,
)
from src.core.rom import AssetType, DecompAssets, RomImage
from src.renderer.camera import Camera, screen_ray, ray_sphere_distance

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='session')
def rom() -> RomImage:
    paths = list(ROOT.glob('*.z64'))
    if not paths:pytest.skip('Local USA Rev 1 ROM not present')
    return RomImage.from_file(paths[0])


@pytest.fixture(scope='session')
def database(rom: RomImage) -> ObjectDatabase:
    return load_object_database(rom)


def synthetic_database(behavior: int = 0) -> ObjectDatabase:
    header = bytearray(128)
    struct.pack_into('>f',header,12,1.5)
    struct.pack_into('>b',header,84,behavior)
    header[96:106] = b'TestObject'
    translation = [512]*512;translation[0]=0;translation[300]=0
    return ObjectDatabase.from_bytes(struct.pack('>512h',*translation),(bytes(header),))


def map_bytes(entry: bytes, padding: bytes = b'') -> bytes:
    return struct.pack('>I',len(entry))+bytes(12)+entry+padding


def record(behavior: int, *, index: int = 0, x: int = 0, z: int = 0, alternate: int = 0) -> bytes:
    raw=bytearray(ENTRY_LAYOUTS[behavior][0]);struct.pack_into('>BBhhh',raw,0,0,len(raw),x,0,z)
    if behavior==13:
        raw[8]=64;raw[9]=index;raw[23]=alternate;raw[26]=0
    return bytes(raw)


def test_object_header_and_9bit_id_translation_and_unknown_bit6() -> None:
    database=synthetic_database()
    entry=struct.pack('>BBhhh',44,0x80|0x40|8,-32768,1024,32767)
    parsed=ObjectMap.from_bytes(map_bytes(entry,b'\0'*4),database,map_id=7)
    obj,=parsed.objects
    assert obj.object_id==300 and obj.definition.header_id==0
    assert obj.definition.name=='TestObject' and obj.definition.scale==1.5
    assert obj.position==(-32768,1024,32767) and obj.size_bit6
    assert obj.raw_data==entry and obj.offset==16 and obj.key==(7,0)
    assert parsed.payload_size==8 and parsed.padding==b'\0'*4
    assert ObjectMap.from_bytes(b'',database,map_id=81).objects==()
    assert ObjectMap.from_bytes(bytes(16),database).objects==()


@pytest.mark.parametrize('data',[
    b'\0'*15,struct.pack('>I',200)+bytes(12),map_bytes(b'\0'*7),
    map_bytes(struct.pack('>BBhhh',0,0,0,0,0)),
    map_bytes(struct.pack('>BBhhh',0,9,0,0,0)+b'\0'),
    map_bytes(struct.pack('>BBhhh',0,16,0,0,0)),
    map_bytes(struct.pack('>BBhhh',1,8,0,0,0)),
    map_bytes(struct.pack('>BBhhh',0,8,0,0,0),b'\0'*8),
    map_bytes(struct.pack('>BBhhh',0,8,0,0,0),b'\x01'),
])
def test_malformed_maps_are_rejected(data: bytes) -> None:
    with pytest.raises(ObjectError):ObjectMap.from_bytes(data,synthetic_database())


def test_known_behavior_requires_exact_entry_size() -> None:
    with pytest.raises(ObjectError,match='expected 28'):
        ObjectMap.from_bytes(map_bytes(struct.pack('>BBhhh',0,8,0,0,0)),synthetic_database(13))
    with pytest.raises(ObjectError):ObjectDatabase.from_bytes(b'\0'*1022,())
    with pytest.raises(ObjectError):ObjectDefinition.from_bytes(b'\0'*119,0)
    header=bytearray(128);struct.pack_into('>f',header,12,float('nan'))
    with pytest.raises(ObjectError):ObjectDefinition.from_bytes(bytes(header),0)


@pytest.mark.parametrize('map_id',range(138))
def test_every_rev1_map_ends_at_exact_payload_boundary(rom: RomImage,database: ObjectDatabase,map_id: int) -> None:
    data=rom.read_asset(AssetType.LEVEL_OBJECT_MAPS,map_id,decompress=True)
    parsed=load_object_map(rom,map_id,database)
    assert sum(obj.byte_size for obj in parsed.objects)==parsed.payload_size
    if not data:
        assert map_id in (81,99) and parsed.header==b''
        return
    assert parsed.header+b''.join(obj.raw_data for obj in parsed.objects)+parsed.padding==data
    assert len(parsed.padding)<8 and not any(parsed.padding)
    offset=16
    for obj in parsed.objects:
        assert obj.offset==offset and obj.raw_data[1]&0x3F==obj.byte_size
        assert database.translation[obj.object_id]==obj.definition.header_id
        assert 0<=obj.definition.header_id<304 and obj.definition.behavior_id>=0
        assert not obj.size_bit6
        offset+=obj.byte_size
    assert offset==16+parsed.payload_size


def test_known_counts_and_source_enum_layout_consistency(rom: RomImage,database: ObjectDatabase) -> None:
    assert len(database.translation)==512 and len(database.definitions)==304
    assert sum(len(load_object_map(rom,i,database).objects) for i in range(138))==9426
    assert [len(load_object_map(rom,i,database).objects) for i in (0,5,73)]==[209,98,86]
    names=re.findall(r'\bBHV_[A-Z0-9_]+',(ROOT/'research/Diddy-Kong-Racing/include/object_behaviors.h').read_text())
    assert tuple(names)==BEHAVIOR_NAMES and len(ENTRY_LAYOUTS)==128
    checkpoint=next(obj for obj in load_object_map(rom,5,database).objects if obj.definition.behavior_id==13)
    assert checkpoint.byte_size==28 and checkpoint.definition.name=='checkpoint'
    assert checkpoint.value('index')==18 and checkpoint.value('vehicleType')==0
    assert len(checkpoint.parameters)==20


def test_checkpoint_alternate_replaces_matching_index_and_preserves_order() -> None:
    db=synthetic_database(13)
    raw=record(13,index=2,x=100,z=100)+record(13,index=0)+record(13,index=1,x=100)+record(13,index=1,x=150,alternate=1)
    objects=ObjectMap.from_bytes(map_bytes(raw),db).objects
    paths=build_race_paths(objects,(0,1,2),vehicle=0)
    assert len(paths)==2 and paths[0].closed and paths[1].alternate
    assert paths[0].object_keys==((0,1),(0,2),(0,0))
    assert paths[1].object_keys==((0,1),(0,3),(0,0))
    np.testing.assert_array_equal(paths[0].points[0],paths[0].points[-1])
    assert not build_race_paths(objects,(0,1,2),vehicle=1)
    assert len(build_race_paths(objects,(0,1,2),vehicle=0,lane=4))==8


def test_ai_paths_follow_adjacency_and_do_not_connect_unlinked_nodes() -> None:
    first=bytearray(record(16));second=bytearray(record(16,x=100));third=bytearray(record(16,x=500))
    for number,raw in enumerate((first,second,third)):
        raw[9]=number;raw[10:14]=bytes([255]*4)
    first[12]=1;second[13]=0
    objects=ObjectMap.from_bytes(map_bytes(bytes(first+second+third)),synthetic_database(16)).objects
    paths=build_race_paths(objects,(0,0,0))
    assert len(paths)==2 and all(path.kind=='ai' and not path.closed for path in paths)
    assert set(path.object_keys for path in paths)=={((0,0),(0,1)),((0,1),(0,0))}


def test_catmull_rom_endpoints_and_straight_line() -> None:
    points=np.array([[0,0,0],[10,0,0],[20,0,0]],np.float32)
    curve=catmull_rom(points,closed=False)
    np.testing.assert_array_equal(curve[0],points[0]);np.testing.assert_array_equal(curve[-1],points[-1])
    assert np.allclose(curve[:,1:],0) and np.all(np.diff(curve[:,0])>0)


def test_vehicle_checkpoint_sets_match_level_header_lookup(rom: RomImage,database: ObjectDatabase) -> None:
    catalog=load_level_catalog(rom)
    assert catalog.levels[0].header.checkpoint_sets==(0,1,2)
    for level in catalog.levels:
        header=level.header
        assert header.checkpoint_sets==struct.unpack_from('>3b',header.raw_data,0x4F)
        objects=tuple(obj for map_id in dict.fromkeys((header.object_map_id,header.secondary_object_map_id)) if map_id>=0
                      for obj in load_object_map(rom,map_id,database).objects)
        for vehicle in range(3):
            paths=build_race_paths(objects,header.checkpoint_sets,vehicle=vehicle,lane=4)
            assert all(np.isfinite(path.points).all() for path in paths)
            assert all(path.checkpoint_set in (-1,header.checkpoint_sets[vehicle]) for path in paths)


def test_ray_picking_hits_nearest_sphere_and_handles_inside_and_behind() -> None:
    camera=Camera(position=np.array([0,0,10],np.float32),yaw=-90,pitch=0)
    matrix=camera.projection_matrix(2)@camera.view_matrix()
    origin,direction=screen_ray(400,200,800,400,matrix)
    np.testing.assert_allclose(direction,[0,0,-1],atol=1e-6)
    a=ray_sphere_distance(origin,direction,np.array([0,0,0],np.float32),1)
    b=ray_sphere_distance(origin,direction,np.array([0,0,-5],np.float32),1)
    assert a is not None and b is not None and a<b
    assert ray_sphere_distance(origin,direction,np.array([5,0,0],np.float32),1) is None
    assert ray_sphere_distance(origin,direction,np.array([0,0,20],np.float32),1) is None
    assert ray_sphere_distance(np.zeros(3,np.float32),direction,np.zeros(3,np.float32),1)==0
    with pytest.raises(ValueError):screen_ray(0,0,0,100,matrix)


def test_extracted_headers_translation_singleton_and_gltf_map(tmp_path: Path) -> None:
    documents={
        'assets.meta.json':{'@dkr-version':'us.v80','assets':{'sections':{
            'ASSET_OBJECTS':{'filename':'objects.meta.json'},'ASSET_LEVEL_OBJECT_MAPS':{'filename':'maps.meta.json'},
            'ASSET_LEVEL_OBJECT_TRANSLATION_TABLE':{'filename':'translation.meta.json'}}}},
        'objects.meta.json':{'files':{'order':['OBJ_CP'],'sections':{'OBJ_CP':{'filename':'checkpoint.json'}}}},
        'maps.meta.json':{'files':{'order':['MAP_TEST'],'sections':{'MAP_TEST':{'filename':'map.json'}}}},
        'translation.meta.json':{'folder':'','filename':'translation.json'},
        'translation.json':{'type':'LevelObjectTranslationTable','table':['OBJ_CP']},
        'checkpoint.json':{'type':'ObjectHeader','behavior':'BHV_CHECKPOINT','internal-name':'checkpoint','scale':1},
        'map.json':{'type':'LevelObjectMap','objects':'map.gltf'},
        'map.gltf':{'asset':{'version':'2.0'},'nodes':[{'name':'objects','children':[1]},
            {'name':'checkpoint','translation':[100,200,-300],'extras':{'id':'OBJ_CP','index':4,'scale':64,'angleY':90,'vehicleType':0}}]},
    }
    for name,document in documents.items():(tmp_path/name).write_text(json.dumps(document))
    source=DecompAssets.from_directory(tmp_path);database=load_object_database(source)
    obj,=load_object_map(source,0,database).objects
    assert obj.definition.name=='checkpoint' and obj.position==(100,200,-300)
    assert obj.value('angleY')==16 and obj.raw_data is None and obj.offset is None and obj.byte_size==28
    documents['map.json']['objects']='../outside.gltf';(tmp_path/'map.json').write_text(json.dumps(documents['map.json']))
    with pytest.raises(ValueError,match='outside'):
        load_object_map(source,0,database)

@pytest.mark.parametrize('field,value', [('vehicleType','plane'),('index',300),('scale',float('nan')),('adjacent',[1])])
def test_malformed_extracted_parameters_are_rejected(tmp_path: Path,field: str,value: object) -> None:
    behavior='BHV_AINODE' if field=='adjacent' else 'BHV_CHECKPOINT'
    documents={
        'assets.meta.json':{'@dkr-version':'us.v80','assets':{'sections':{
            'ASSET_OBJECTS':{'filename':'objects.meta.json'},'ASSET_LEVEL_OBJECT_MAPS':{'filename':'maps.meta.json'},
            'ASSET_LEVEL_OBJECT_TRANSLATION_TABLE':{'filename':'translation.meta.json'}}}},
        'objects.meta.json':{'files':{'order':['OBJ_TEST'],'sections':{'OBJ_TEST':{'filename':'object.json'}}}},
        'maps.meta.json':{'files':{'order':['MAP_TEST'],'sections':{'MAP_TEST':{'filename':'map.json'}}}},
        'translation.meta.json':{'filename':'translation.json'},
        'translation.json':{'type':'LevelObjectTranslationTable','table':['OBJ_TEST']},
        'object.json':{'type':'ObjectHeader','behavior':behavior,'internal-name':'test'},
        'map.json':{'type':'LevelObjectMap','objects':'map.gltf'},
        'map.gltf':{'nodes':[{'name':'objects','children':[1]},{'translation':[0,0,0],'extras':{'id':'OBJ_TEST',field:value}}]},
    }
    for name,document in documents.items():(tmp_path/name).write_text(json.dumps(document))
    source=DecompAssets.from_directory(tmp_path)
    with pytest.raises(ObjectError,match='parameter'):
        load_object_map(source,0,load_object_database(source))
