"""Object mesh/animation format, scene targeting and displayed-pose picking."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct

import numpy as np
import pytest

from src.core.level_model import ModelError
from src.core.level_header import load_level_catalog
from src.core.object_models import (ObjectLibrary, ObjectModel, AnimationClip,
    ModelInstance, model_instances, ray_model_distance, preview_colors)
from src.core.textures import SpriteInstance
from src.core.objects import ObjectDefinition, load_object_database, load_object_map
from src.core.rom import AssetType, RomImage

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(ROOT.glob('*.z64'))
    if not paths:
        pytest.skip('Local Rev1 ROM absent')
    return RomImage.from_file(paths[0])


def synthetic_model() -> ObjectModel:
    raw = bytearray(224)
    struct.pack_into('>3I',raw,0,128,128,158)
    struct.pack_into('>4h',raw,0x22,0,3,1,1)
    struct.pack_into('>I',raw,0x2c,len(raw))
    struct.pack_into('>I',raw,0x38,174)
    struct.pack_into('>hI',raw,0x4a,1,198)
    for index,position in enumerate(((10,20,30),(1,2,3),(10,20,30))):
        struct.pack_into('>3h4B',raw,128+index*10,*position,255,255,255,255)
    struct.pack_into('>4B6h',raw,158,0,0,1,2,*([0]*6))
    struct.pack_into('>BbhhBBI',raw,174,255,0,0,0,255,0,0)
    struct.pack_into('>BbhhBBI',raw,186,0,0,3,1,0,0,0)
    struct.pack_into('>3h',raw,198,0,-1,0)
    return ObjectModel.from_bytes(bytes(raw))


def test_signed_delta_static_vertices_fraction_and_clamp() -> None:
    model = synthetic_model()
    # Base offset (2,-3,4), then signed increments (-5,7,-9), (6,-8,10).
    raw = struct.pack('>I',3)+bytes(12)+struct.pack('>3h',2,-3,4)+bytes(12)+struct.pack('>3b',-5,7,-9)+bytes(12)+struct.pack('>3b',6,-8,10)
    clip = AnimationClip.from_bytes(raw,model)
    np.testing.assert_array_equal(clip.pose(model,0),[[12,17,34],[1,2,3],[12,17,34]])
    np.testing.assert_array_equal(clip.pose(model,8)[0],[9,20,29])
    np.testing.assert_array_equal(clip.pose(model,16)[0],[7,24,25])
    np.testing.assert_array_equal(clip.pose(model,-1),clip.pose(model,0))
    np.testing.assert_array_equal(clip.pose(model,9999),clip.pose(model,31))
    assert not clip.positions.flags.writeable and not model.animated_indices.flags.writeable


@pytest.mark.parametrize('offset,format,value',[(0x2c,'I',999),(0x24,'h',-1),(0x28,'h',100),(0x4a,'h',4),(0x4c,'I',2),(198,'h',2),(158+1,'B',3)])
def test_malformed_models(offset: int, format: str, value: int) -> None:
    raw = bytearray(synthetic_model().raw_data)
    struct.pack_into('>'+format,raw,offset,value)
    with pytest.raises(ModelError):
        ObjectModel.from_bytes(bytes(raw))


@pytest.mark.parametrize('raw',[b'',bytes(4),struct.pack('>I',999999)+bytes(64),struct.pack('>I',2)+bytes(12)])
def test_malformed_animations(raw: bytes) -> None:
    with pytest.raises(ModelError):
        AnimationClip.from_bytes(raw,synthetic_model())


def test_transform_matches_source_and_picking() -> None:
    definition = ObjectDefinition(0,'Test',2,1)
    instance = ModelInstance(0,definition,0,(10,20,30),2,(np.pi/2,0,0))
    point = instance.transform@np.array([0,0,1,1])
    np.testing.assert_allclose(point,[12,20,30,1],atol=1e-5)
    vertices = np.array([[-1,-1,5],[1,-1,5],[0,1,5]],np.float32)
    faces = np.array([[0,1,2]],np.uint32)
    assert ray_model_distance(np.zeros(3,np.float32),np.array([0,0,1],np.float32),vertices,faces) == pytest.approx(5)
    assert ray_model_distance(np.array([10,0,0],np.float32),np.array([0,0,1],np.float32),vertices,faces) is None


def test_sprite_counter_normalization_and_reverse_wrap() -> None:
    sprite = SpriteInstance(0,0,(0,0,0),1.,(),((),(),(),()),8.)
    assert [sprite.frame_at(t/60) for t in (0,7,8,16,24,31,32)] == [0,0,1,2,3,3,0]
    assert replace(sprite,frame_speed=-8).frame_at(1/60) == 3
    assert replace(sprite,initial_frame=128).frame_at(0) == 2
    assert replace(sprite,frames=()).frame_at(999) == 0


def test_baked_colors_survive_preview_light() -> None:
    model = synthetic_model()
    np.testing.assert_array_equal(preview_colors(model,model.mesh.segments[0].vertices),np.ones((3,4),np.float32))


def test_all_390_models_and_470_clips(rom: RomImage) -> None:
    library = ObjectLibrary(rom)
    assert rom.count(AssetType.OBJECT_MODELS) == 390
    assert rom.count(AssetType.OBJECT_ANIMATIONS) == 470
    clips = 0
    for index in range(390):
        model = library.model(index)
        assert model.mesh.vertex_count > 0
        assert model.mesh.indices.max(initial=0) < model.mesh.vertex_count
        for clip_index in range(library.clip_count(index)):
            clip = library.clip(index,clip_index)
            assert clip is not None
            for frame in (0,8,(clip.frame_count-1)*16-1):
                pose = clip.pose(model,frame)
                assert pose.shape == (model.mesh.vertex_count,3) and np.isfinite(pose).all()
                np.testing.assert_array_equal(pose[model.animated_indices < 0],model.mesh.segments[0].vertices[model.animated_indices < 0])
            clips += 1
    assert clips == 470


def test_ancient_lake_ambient_actor_and_helpers(rom: RomImage) -> None:
    database = load_object_database(rom)
    catalog = load_level_catalog(rom)
    header = next(level.header for level in catalog.levels if level.name == 'Ancient Lake')
    objects = tuple(obj for map_id in (header.object_map_id,header.secondary_object_map_id)
                    for obj in load_object_map(rom,map_id,database).objects)
    ambient = model_instances(objects,database,-2)
    dinosaur = [instance for instance in ambient if instance.definition.name == 'Dinosaur2']
    assert len(dinosaur) == 1 and dinosaur[0].model_id == 240
    assert objects[dinosaur[0].object_index].definition.behavior_id == 49
    assert all(instance.definition.behavior_id not in (13,49,51,73) for instance in ambient)
    intro = model_instances(objects,database,10)
    assert len(intro) > len(ambient) and any(instance.definition.name == 'AnimGenie' for instance in intro)
    moved = list(objects)
    selected = dinosaur[0].object_index
    moved[selected] = replace(moved[selected],position=(1,2,3))
    result = model_instances(tuple(moved),database,-2)
    assert next(i for i in result if i.object_index == selected).position == (1,2,3)


def test_every_level_model_target_resolves(rom: RomImage) -> None:
    database = load_object_database(rom)
    library = ObjectLibrary(rom)
    for level in load_level_catalog(rom).levels:
        ids = dict.fromkeys(i for i in (level.header.object_map_id,level.header.secondary_object_map_id) if i >= 0)
        objects = tuple(obj for map_id in ids for obj in load_object_map(rom,map_id,database).objects)
        channels = {0,*[int(obj.value('channel',0)) for obj in objects if obj.definition.behavior_id == 49]}
        for channel in channels:
            for instance in model_instances(objects,database,channel):
                library.model(instance.model_id)
                library.clip(instance.model_id,instance.clip_index)
