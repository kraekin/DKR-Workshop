"""ROM sprite tables, multi-tile anchors and world-object selection, headless."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image
import pytest

from src.core.level_header import load_level_catalog
from src.core.objects import ObjectDatabase, ObjectDefinition, ObjectError, ObjectMap, load_object_database, load_object_map
from src.core.rom import AssetType, DecompAssets, RomImage
from src.core.textures import SpriteAsset, Texture, TextureError, load_level_sprites, load_sprite, load_texture, sprite_tiles

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def rom() -> RomImage:
    paths = list(ROOT.glob("*.z64"))
    if not paths:
        pytest.skip("Local USA Rev 1 ROM not present")
    return RomImage.from_file(paths[0])


def texture_bytes(*, x: int = 0, y: int = 0, count: int = 1, stride: int = 48) -> bytes:
    raw = bytearray(32)
    raw[:3] = bytes((2, 2, 0x10))  # opaque RGBA32, 2x2
    struct.pack_into(">bb", raw, 3, x, y)
    raw[18] = count
    struct.pack_into(">h", raw, 22, stride)
    return bytes(raw) + bytes.fromhex("ff0000ff00ff00ff0000ffffffffffff")


def object_database(behavior: int = 2) -> ObjectDatabase:
    raw = bytearray(128)
    struct.pack_into(">fI", raw, 12, 3.0, 120)
    raw[83:86] = bytes((1, behavior, 2))
    raw[96:100] = b"Tree"
    struct.pack_into(">2I", raw, 120, 0, 1)
    return ObjectDatabase.from_bytes(struct.pack(">512h", 0, *([512] * 511)), (bytes(raw),))


def test_sprite_header_and_frame_ranges_include_empty_frames() -> None:
    data = struct.pack(">4hI", 12, 3, -80, 122, 0) + bytes((0, 2, 2, 5))
    sprite = SpriteAsset.from_bytes(data, sprite_id=7)
    assert sprite.sprite_id == 7 and sprite.anchor == (-80, 122)
    assert sprite.frame_count == 3 and sprite.raw_data == data
    assert sprite.texture_ids(0) == (12, 13)
    assert sprite.texture_ids(1) == () and sprite.texture_ids(2) == (14, 15, 16)
    with pytest.raises(TextureError):
        sprite.texture_ids(3)


@pytest.mark.parametrize("data", [
    bytes(13), struct.pack(">4hI", -1, 1, 0, 0, 0) + bytes((0, 1)),
    struct.pack(">4hI", 0, 0, 0, 0, 0) + bytes(2),
    struct.pack(">4hI", 0, 3, 0, 0, 0) + bytes((0, 1)),
    struct.pack(">4hI", 0, 1, 0, 0, 0) + bytes((1, 2)),
    struct.pack(">4hI", 0, 2, 0, 0, 0) + bytes((0, 2, 1)),
])
def test_invalid_sprite_headers(data: bytes) -> None:
    with pytest.raises(TextureError):
        SpriteAsset.from_bytes(data)


def test_signed_tile_offsets_and_source_pixel_extents() -> None:
    sprite = SpriteAsset(0, 0, (10, 20), (0, 2))
    textures = {i: Texture.from_bytes(texture_bytes(x=x, y=y), texture_id=i)
                for i, (x, y) in enumerate(((-3, -7), (12, 30)))}
    tiles = sprite_tiles(sprite, textures)
    assert (tiles[0].left, tiles[0].right, tiles[0].top, tiles[0].bottom) == (-13, -12, 26, 25)
    assert (tiles[1].left, tiles[1].right, tiles[1].top, tiles[1].bottom) == (2, 3, -11, -12)


def test_final_frame_stride_may_include_unstored_alignment_padding() -> None:
    assert Texture.from_bytes(texture_bytes(stride=64)).frames[0].header.frame_size == 64
    with pytest.raises(TextureError):
        Texture.from_bytes(texture_bytes(stride=64, count=2))
    with pytest.raises(TextureError):
        Texture.from_bytes(texture_bytes(stride=40))


def test_object_model_ids_use_correct_pointer_and_signed_count() -> None:
    definition = object_database().definitions[0]
    assert definition.model_type == 1 and definition.behavior_id == 2 and definition.model_ids == (0, 1)
    for pointer, count in ((0, 2), (124, 2), (120, -1)):
        raw = bytearray(definition.raw_data)
        struct.pack_into(">I", raw, 16, pointer)
        struct.pack_into(">b", raw, 85, count)
        with pytest.raises(ObjectError):
            ObjectDefinition.from_bytes(bytes(raw), 0)


@pytest.mark.parametrize("behavior,parameters,expected_id,expected_scale", [
    (2, bytes((1, 32, 0, 0)), 1, 1.5),
    (2, bytes((255, 0, 0, 0)), 0, 3 * 10 / 64),
    (17, bytes((0, 1, 128, 0)), 1, 6.0),
    (28, bytes((0, 32, 0, 0)), 0, 1.5),
    (32, b"", 0, 3.0),
    (10, bytes(2), None, None),  # invisible camera helper also references a sprite
])
def test_behavior_selection_scale_fallback_and_hidden_helpers(
    rom: RomImage, behavior: int, parameters: bytes, expected_id: int | None, expected_scale: float | None,
) -> None:
    entry = struct.pack(">BBhhh", 0, 8 + len(parameters), 10, 20, -30) + parameters
    objects = ObjectMap.from_bytes(struct.pack(">I", len(entry)) + bytes(12) + entry, object_database(behavior)).objects
    sprites = {i: SpriteAsset(i, i, (0, 0), (0, 1)) for i in range(2)}
    textures = {i: Texture.from_bytes(texture_bytes(), texture_id=i) for i in range(2)}
    instances = load_level_sprites(rom, objects, sprites, textures)
    if expected_id is None:
        assert not instances
    else:
        instance, = instances
        assert instance.sprite_id == expected_id and instance.scale == expected_scale
        assert instance.object_index == 0 and instance.position == (10, 20, -30)
        assert instance.upright == (behavior == 2)


def test_every_rom_sprite_frame_and_2d_texture_decodes(rom: RomImage) -> None:
    assert rom.count(AssetType.SPRITES) == 193 and rom.count(AssetType.TEXTURES_2D) == 916
    textures = {i: load_texture(rom, i, asset_type=AssetType.TEXTURES_2D) for i in range(916)}
    counts: Counter[int] = Counter()
    for i in range(193):
        sprite = load_sprite(rom, i)
        for frame in range(sprite.frame_count):
            tiles = sprite_tiles(sprite, textures, frame)
            counts[len(tiles)] += 1
            for tile in tiles:
                assert tile.frame.pixels.shape == (tile.frame.header.height, tile.frame.header.width, 4)
                assert tile.right >= tile.left and tile.top >= tile.bottom
    assert counts == {1: 508, 2: 48, 3: 17, 4: 13, 0: 10, 6: 2, 5: 2}
    beach_tree = sprite_tiles(load_sprite(rom, 107), textures)
    assert len(beach_tree) == 3
    assert (min(t.left for t in beach_tree), max(t.right for t in beach_tree),
            max(t.top for t in beach_tree), min(t.bottom for t in beach_tree)) == (-34, 33, 116, -6)


def test_all_levels_resolve_world_sprites_and_cache_separately(rom: RomImage) -> None:
    database = load_object_database(rom)
    sprite_cache: dict[int, SpriteAsset] = {}
    texture_cache: dict[int, Texture] = {}
    for level in load_level_catalog(rom).levels:
        header = level.header
        objects = tuple(obj for map_id in dict.fromkeys((header.object_map_id, header.secondary_object_map_id))
                        if map_id >= 0 for obj in load_object_map(rom, map_id, database).objects)
        instances = load_level_sprites(rom, objects, sprite_cache, texture_cache)
        assert all(objects[s.object_index].definition.model_type == 1 and s.scale > 0 for s in instances)
        assert all(s.upright == (objects[s.object_index].definition.behavior_id == 2) for s in instances)
        if level.name == "Ancient Lake":
            assert len(instances) == 67 and sum(len(s.tiles) for s in instances) == 140
            assert sum(objects[s.object_index].definition.behavior_id == 2 for s in instances) == 22
    assert sprite_cache and texture_cache


def test_extracted_sprite_and_signed_texture_offsets(tmp_path: Path) -> None:
    Image.fromarray(np.full((2, 2, 4), 255, np.uint8)).save(tmp_path / "tile.png")
    docs = {
        "assets.meta.json": {"@dkr-version": "us.v80", "assets": {"sections": {
            "ASSET_TEXTURES_2D": {"filename": "textures.meta.json"},
            "ASSET_SPRITES": {"filename": "sprites.meta.json"},
            "ASSET_OBJECTS": {"filename": "objects.meta.json"},
            "ASSET_LEVEL_OBJECT_TRANSLATION_TABLE": {"filename": "translation.meta.json"}}}},
        "textures.meta.json": {"files": {"order": ["TILE"], "sections": {"TILE": {"filename": "texture.json"}}}},
        "sprites.meta.json": {"files": {"order": ["TREE"], "sections": {"TREE": {"filename": "sprite.json"}}}},
        "texture.json": {"format": "RGBA16", "images": ["tile.png"], "sprite-x": -5, "sprite-y": -12},
        "sprite.json": {"type": "Sprite", "start-texture": "TILE", "unk4": 10, "unk6": 20, "frame-tex-count": [1, 0]},
        "objects.meta.json": {"files": {"order": ["OBJECT_TREE"], "sections": {"OBJECT_TREE": {"filename": "object.json"}}}},
        "object.json": {"type": "ObjectHeader", "internal-name": "Tree", "behavior": "BHV_SCENERY", "scale": 3,
                        "model-type": "OBJECT_MODEL_TYPE_SPRITE_BILLBOARD", "models": ["TREE"]},
        "translation.meta.json": {"filename": "translation.json"},
        "translation.json": {"type": "LevelObjectTranslationTable", "table": ["OBJECT_TREE"]},
    }
    for name, document in docs.items():
        (tmp_path / name).write_text(json.dumps(document))
    source = DecompAssets.from_directory(tmp_path)
    definition = load_object_database(source).resolve(0)
    assert definition.model_type == 1 and definition.model_ids == (0,) and definition.scale == 3
    sprite = load_sprite(source, 0)
    texture = load_texture(source, 0, asset_type=AssetType.TEXTURES_2D)
    tile, = sprite_tiles(sprite, {0: texture})
    assert sprite.frame_offsets == (0, 1, 1) and (tile.left, tile.top) == (-15, 31)
    docs["sprite.json"]["frame-tex-count"] = [2]
    (tmp_path / "sprite.json").write_text(json.dumps(docs["sprite.json"]))
    with pytest.raises(TextureError, match="exceeds"):
        load_sprite(source, 0)
