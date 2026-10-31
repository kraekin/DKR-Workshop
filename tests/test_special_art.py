"""Source-built artwork, clipped decals and preview-only behavior, headless."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
import json
import math
import struct

import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.level_header import load_level_catalog
from src.core.level_model import Bounds, LevelModel, LevelModelSegment, TriangleBatchInfo, load_level_model
from src.core.object_models import ray_model_distance
from src.core.objects import LevelObject, ObjectDefinition, ObjectParameter, load_object_database, load_object_map
from src.core.rom import AssetType, RomImage, DecompAssets
from src.core.special_art import (PORTRAIT_NAMES, ShadowSpec, SpecialLibrary, SpecialInstance,
                                  _animal, artwork_note, projected_zipper, shadow_spec)
from src.core.textures import Texture, TextureFrame

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(ROOT.glob('*.z64'))
    if not paths:
        pytest.skip('Local Rev 1 ROM absent')
    return RomImage.from_file(paths[0])


def frame() -> TextureFrame:
    raw = bytearray(32)
    raw[:3] = bytes((8, 4, 0x10))
    raw[18] = 1
    struct.pack_into('>h', raw, 22, 160)
    return Texture.from_bytes(bytes(raw)+bytes((255, 255, 255, 255))*32).frames[0]


def obj(behavior: int = 82, position: tuple[int, int, int] = (0, 0, 0), **parameters: int) -> LevelObject:
    return LevelObject(0, 0, 0, 0, ObjectDefinition(0, 'Test', behavior, 2., model_type=4, model_ids=(0,)),
        position, 16, False, tuple(ObjectParameter(name, 8+i, 'B', value) for i, (name, value) in enumerate(parameters.items())), None)


def floor_model(flags: int = 0) -> LevelModel:
    vertices = np.array(((-100, -30, -100), (100, 10, -100), (100, 30, 100), (-100, -10, 100)), np.float32)
    indices = np.array(((0, 2, 1), (0, 3, 2)), np.uint32)
    colors = np.full((4, 4), 255, np.uint8)
    bounds = Bounds.from_vertices(vertices)
    batch = TriangleBatchInfo(255, 0, 0, 0, 0, 0, flags)
    terminal = TriangleBatchInfo(255, 0, 4, 2, 0, 0, 0)
    segment = LevelModelSegment(0, vertices, colors, colors, indices, np.zeros(2, np.uint8),
        np.zeros((2, 3, 2), np.int16), (batch,), terminal, bounds, bounds, 0, 0, 1)
    return LevelModel(0, (segment,), (), (), bounds, bounds, np.column_stack((vertices, colors/255)).astype(np.float32), indices, 0)


def test_decal_clips_slopes_and_source_uv_orientation() -> None:
    item = projected_zipper(floor_model(), obj(scale=64, angleY=0), ShadowSpec(1., 0, -100, 10), frame(), 7)
    assert item is not None and item.object_index == 7 and item.kind == 'zipper'
    assert len(item.indices) >= 2 and item.indices.max() < len(item.vertices)
    xyz = item.vertices
    assert np.all(np.abs(xyz[:, (0, 2)]) <= 10.001)
    np.testing.assert_allclose(xyz[:, 1], xyz[:, 0]*.2+xyz[:, 2]*.1+2, atol=.0001)
    uv = item.uvs
    corners = xyz[item.indices]
    np.testing.assert_allclose(uv[:, :, 0], .5+corners[:, :, 0]*1.4142/20, atol=.0001)
    # Source uses WIDTH for both UV centers/scales, including non-square art.
    np.testing.assert_allclose(uv[:, :, 1], 1.+corners[:, :, 2]*1.4142/10, atol=.0001)
    rotated = projected_zipper(floor_model(), obj(scale=64, angleY=16), ShadowSpec(1., 0, -100, 10), frame(), 7)
    np.testing.assert_allclose(rotated.uvs[:, :, 0], .5-corners[:, :, 2]*1.4142/20, atol=.0001)
    np.testing.assert_allclose(rotated.uvs[:, :, 1], 1.+corners[:, :, 0]*1.4142/10, atol=.0001)
    assert not item.vertices.flags.writeable and not item.uvs.flags.writeable


@pytest.mark.parametrize('flags', (0x100, 0x800, 0x2000, 0x4000, 0x6900))
def test_shadow_ineligible_faces_are_excluded(flags: int) -> None:
    assert projected_zipper(floor_model(flags), obj(scale=64), ShadowSpec(1., 0, -100, 10), frame(), 0) is None


@pytest.mark.parametrize('position', ((1000, 0, 1000), (0, 1000, 0), (0, -1000, 0)))
def test_no_floating_decal_when_track_is_out_of_range(position: tuple[int, int, int]) -> None:
    assert projected_zipper(floor_model(), obj(position=position), ShadowSpec(1., 0, -100, 10), frame(), 0) is None


def test_decal_scale_floor_and_height_fade() -> None:
    spec = ShadowSpec(1., 0, -100, 10)
    minimum = projected_zipper(floor_model(), obj(scale=0), spec, frame(), 0)
    ten = projected_zipper(floor_model(), obj(scale=10), spec, frame(), 0)
    np.testing.assert_array_equal(minimum.vertices, ten.vertices)
    high = projected_zipper(floor_model(), obj(position=(0, 50, 0), scale=64), spec, frame(), 0)
    assert 0 < high.alpha < 1
    assert high.uvs.max() > ten.uvs.max()


def test_vertical_degenerate_facets_do_not_produce_decals() -> None:
    model = floor_model()
    segment = replace(model.segments[0], vertices=np.array(((0, 0, 0), (0, 100, 0), (0, 100, 100), (0, 0, 100)), np.float32))
    assert projected_zipper(replace(model, segments=(segment,)), obj(), ShadowSpec(1., 0, -100, 10), frame(), 0) is None


@pytest.mark.parametrize('fish', (False, True))
def test_source_strip_winding_uvs_and_picking(fish: bool) -> None:
    vertices, indices, uv = _animal(frame(), fish)
    assert vertices.shape == (6, 3) and indices.shape == (8, 3)
    np.testing.assert_array_equal(indices[4:], indices[:4, (0, 2, 1)])
    np.testing.assert_array_equal(uv[4:], uv[:4, (0, 2, 1)])
    assert uv.min() == 0 and uv[:, :, 0].max() == 7/8 and uv[:, :, 1].max() == 3/4
    if fish:
        np.testing.assert_array_equal(vertices[:, 2], (-64, -64, 32, 32, 64, 64))
        hit = ray_model_distance(np.array((100, 0, 0), np.float32), np.array((-1, 0, 0), np.float32), vertices, indices)
    else:
        np.testing.assert_array_equal(vertices[:, 2], (32, -32, 32, -32, 32, -32))
        hit = ray_model_distance(np.array((0, 100, 0), np.float32), np.array((0, -1, 0), np.float32), vertices, indices)
    assert hit == 100


def test_idle_wings_deterministic_scrub_and_moth_variant() -> None:
    texture = frame()
    v, i, uv = _animal(texture, False)
    item = SpecialInstance(0, 'butterfly', texture, v, i, uv, (10., 20., 30.), (.2,)*3)
    first = item.pose(0)
    other = item.pose(.7)
    assert not np.array_equal(first, other)
    np.testing.assert_array_equal(item.pose(0), first)
    np.testing.assert_array_equal(item.pose(-1), first)
    np.testing.assert_allclose(item.pose(256/60), first)
    assert not np.array_equal(v, first) and v[0, 0] == -64  # source arrays are immutable
    moth = replace(item, variant=2)
    np.testing.assert_array_equal(moth.pose(0), moth.pose(19))  # source idle forces frame 120


def test_fish_figure_eight_home_heading_scale_and_tail() -> None:
    texture = frame()
    v, i, uv = _animal(texture, True)
    item = SpecialInstance(0, 'fish', texture, v, i, uv, (10., 20., 30.), (2., 1., 2.), radius=100., speed=64.)
    # At phase 0x4000 the source figure-eight starts at home; body pairs remain
    # centered in local Y despite render_misc_model's independent height scale.
    first = item.pose(0)
    np.testing.assert_allclose(first[:4, 1].mean(), 20.)
    np.testing.assert_allclose(np.ptp(first[:, 1]), 128.)
    second = item.pose(.2)
    assert not np.array_equal(first, second)
    np.testing.assert_array_equal(item.pose(.2), second)
    np.testing.assert_array_equal(item.pose(0), first)
    stationary = replace(item, radius=0.)
    np.testing.assert_array_equal(stationary.pose(0), stationary.pose(20))


def test_header_shadow_fields_and_signed_texture_section(rom: RomImage) -> None:
    d = next(d for d in load_object_database(rom).definitions if d.behavior_id == 82)
    spec = shadow_spec(rom, d)
    assert spec.texture_id == 16 and spec.bottom == -100 and spec.top == 10
    raw = bytearray(d.raw_data)
    struct.pack_into('>h', raw, 0x34, -32752)
    assert shadow_spec(rom, replace(d, raw_data=bytes(raw))).texture_id == 0x8010
    struct.pack_into('>f', raw, 4, float('nan'))
    with pytest.raises(ValueError, match='shadow'):
        shadow_spec(rom, replace(d, raw_data=bytes(raw)))
    struct.pack_into('>h', raw, 0x32, 0)
    assert shadow_spec(rom, replace(d, raw_data=bytes(raw))) is None


def test_all_stock_levels_special_artwork_is_valid_and_never_edits(rom: RomImage) -> None:
    catalog = load_level_catalog(rom)
    db = load_object_database(rom)
    library = SpecialLibrary(rom)
    kinds: Counter[str] = Counter()
    zipper_keys: set[tuple[int, int]] = set()
    missing: list[tuple[int, int, int]] = []
    for level in catalog.levels:
        maps = dict.fromkeys((level.header.object_map_id, level.header.secondary_object_map_id))
        objects = tuple(o for m in maps if m >= 0 for o in load_object_map(rom, m, db).objects)
        before = tuple(o.raw_data for o in objects)
        instances = library.instances(objects, load_level_model(rom, level.header.geometry_id))
        covered = {item.object_index for item in instances}
        zipper_keys.update(objects[item.object_index].key for item in instances if item.kind == 'zipper')
        missing.extend((level.index, o.map_id, o.index) for i, o in enumerate(objects) if o.definition.behavior_id == 82 and i not in covered)
        for item in instances:
            kinds[item.kind] += 1
            assert item.indices.max() < len(item.vertices)
            assert np.isfinite(item.uvs).all() and 0 <= item.alpha <= 1
            for seconds in (0., .4, 3., 30.):
                assert np.isfinite(item.pose(seconds)).all()
        assert before == tuple(o.raw_data for o in objects)
    assert set(kinds) == {'zipper', 'fish', 'butterfly', 'portrait'}
    assert not missing, f'Zippers without eligible projection: {missing}'
    assert len(zipper_keys) == 83  # Other nine reside in maps unreferenced by stock level headers.


def test_physical_art_fallbacks_and_helpers_stay_invisible(rom: RomImage) -> None:
    library = SpecialLibrary(rom)
    d = next(d for d in load_object_database(rom).definitions if d.behavior_id == 61)
    bad = replace(obj(61, unkA=255, unkB=20), definition=d)
    good = replace(obj(61, unkA=0, unkB=20), definition=d)
    one = library.instances((bad,), None)[0]
    two = library.instances((good,), None)[0]
    assert one.texture is two.texture and one.scale == (.2,)*3
    assert not library.instances((obj(89), obj(13), obj(16), obj(49)), floor_model())
    assert 'live racer' in artwork_note(89) and not artwork_note(13)


def test_portraits_follow_character_enum_and_stored_transform(rom: RomImage) -> None:
    d = next(d for d in load_object_database(rom).definitions if d.behavior_id == 47)
    library = SpecialLibrary(rom)
    flag = replace(obj(47, radius=32, angleY=16), definition=d)
    assert PORTRAIT_NAMES[9] == 'Diddy' and PORTRAIT_NAMES[1] == 'Bumper'
    assert not library.instances((flag,), None, -1)
    for character, texture_id in enumerate(d.model_ids):
        item = library.instances((flag,), None, character)[0]
        assert item.texture is library.frame(AssetType.TEXTURES_2D, texture_id)
        assert item.scale == (d.scale*.5,)*3 and item.yaw == math.pi/2
        np.testing.assert_allclose(item.pose(0)[:, 0], 0., atol=.0001)


def test_special_art_uses_image_overlays_and_preserves_project_format(rom: RomImage) -> None:
    session = EditSession(rom)
    d = next(d for d in session.database.definitions if d.behavior_id == 3)
    fish = replace(obj(3, unkB=0, unkC=100, unkD=50, unk8=0, unkE=0), definition=d)
    key = AssetType.TEXTURES_2D, d.model_ids[0]
    original = session.image_texture(*key).frames[0].pixels
    pixels = original.copy(); pixels[0, 0] = (255, 0, 0, 255)
    assert session.import_image(*key, 0, pixels)
    signature = session._signature()
    item = SpecialLibrary(session.asset_source).instances((fish,), None)[0]
    np.testing.assert_array_equal(item.texture.pixels, session.image_texture(*key).frames[0].pixels)
    item.pose(10.)
    assert session._signature() == signature and session.project_document()['version'] == 6
    session.undo()
    restored = SpecialLibrary(session.asset_source).instances((fish,), None)[0]
    np.testing.assert_array_equal(restored.texture.pixels, original)
    assert not session.dirty


def test_extracted_misc_texture_ids_and_shadow_json(tmp_path: Path) -> None:
    documents = {
        'assets.meta.json': {'@dkr-version': 'us.v80', 'assets': {'order': ['ASSET_OBJECTS', 'ASSET_LEVEL_OBJECT_TRANSLATION_TABLE', 'ASSET_TEXTURES_2D'],
            'sections': {'ASSET_OBJECTS': {'filename': 'objects.meta.json'},
                         'ASSET_LEVEL_OBJECT_TRANSLATION_TABLE': {'filename': 'translation.meta.json'},
                         'ASSET_TEXTURES_2D': {'filename': 'textures.meta.json'}}}},
        'objects.meta.json': {'files': {'order': ['FISH'], 'sections': {'FISH': {'filename': 'object.json'}}}},
        'translation.meta.json': {'filename': 'translation.json'},
        'translation.json': {'type': 'LevelObjectTranslationTable', 'table': ['FISH']},
        'textures.meta.json': {'files': {'order': ['FISH_TEX'], 'sections': {'FISH_TEX': {'filename': 'texture.bin'}}}},
        'object.json': {'type': 'ObjectHeader', 'internal-name': 'Fish', 'behavior': 'BHV_FISH',
            'model-type': 'OBJECT_MODEL_TYPE_MISC', 'models': ['FISH_TEX'],
            'shadow-group': 1, 'shadow-scale': 2., 'unknown': {'unk34': 0, 'unk42': -70, 'unk44': 10}},
    }
    for name, document in documents.items():
        (tmp_path/name).write_text(json.dumps(document))
    source = DecompAssets.from_directory(tmp_path)
    d = load_object_database(source).resolve(0)
    assert d.model_type == 4 and d.model_ids == (0,)
    assert shadow_spec(source, d) == ShadowSpec(2., 0, -70, 10)
    # Decoded JSON source may use raw binary textures too.
    raw = bytearray(32); raw[:3] = (8, 4, 0x10); raw[18] = 1
    struct.pack_into('>h', raw, 22, 160)
    (tmp_path/'texture.bin').write_bytes(bytes(raw)+bytes((255, 255, 255, 255))*32)
    fish = replace(obj(3, unkB=0, unkC=100, unkD=100), definition=d)
    assert len(SpecialLibrary(source).instances((fish,), None)) == 1
