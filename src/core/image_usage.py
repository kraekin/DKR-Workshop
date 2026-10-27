"""Known image dependencies from existing models, sprites, headers and maps.

This deliberately labels known asset references; compiled HUD/menu/dynamic
spawns can have additional uses that are not enumerated by these data tables.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct
from src.core.rom import AssetType, RomImage, DecompAssets
from src.core.level_header import load_level_catalog
from src.core.level_model import load_level_model
from src.core.objects import ObjectDatabase
from src.core.object_dependencies import DefinitionUse, definition_dependencies
from src.core.textures import load_sprite

ImageKey = tuple[AssetType, int]


@dataclass
class ImageUses:
    direct: dict[ImageKey, set[str]] = field(default_factory=dict)
    levels: dict[ImageKey, set[str]] = field(default_factory=dict)

    def add(self, key: ImageKey, text: str, levels: set[str]) -> None:
        self.direct.setdefault(key, set()).add(text)
        self.levels.setdefault(key, set()).update(levels)


def build_image_uses(source: RomImage | DecompAssets, database: ObjectDatabase, *,
                     dependencies: dict[int, DefinitionUse] | None = None) -> ImageUses:
    result = ImageUses()
    catalog = load_level_catalog(source)
    model_levels: dict[int, set[str]] = {}
    if dependencies is None:
        dependencies = definition_dependencies(source, database)
    for level in catalog.levels:
        name = f"{level.index}: {level.name}"
        model_levels.setdefault(level.header.geometry_id, set()).add(name)
        header = level.header
        if header.special_sky == -1:
            section = AssetType.TEXTURES_3D if header.special_sky_texture & 0x8000 else AssetType.TEXTURES_2D
            result.add((section, header.special_sky_texture & 0x7FFF), f"Level {level.index} flash sky", {name})
    object_levels: dict[int, set[str]] = {}
    for definition in database.definitions:
        levels = set(dependencies[definition.header_id].levels)
        if definition.model_type == 0:
            for index in definition.model_ids:
                object_levels.setdefault(index, set()).update(levels)
        elif definition.model_type in (1, 2):
            for index in definition.model_ids:
                result.add((AssetType.SPRITES, index), f"Object header {definition.header_id}: {definition.name}", levels)
        elif definition.model_type == 4:
            for index in definition.model_ids:
                section = AssetType.TEXTURES_3D if index & 0x8000 else AssetType.TEXTURES_2D
                result.add((section, index & 0x7FFF), f"Object header {definition.header_id}: {definition.name}", levels)
        if definition.behavior_id == 82:
            from src.core.special_art import shadow_spec
            spec = shadow_spec(source, definition)
            if spec is not None:
                section = AssetType.TEXTURES_3D if spec.texture_id & 0x8000 else AssetType.TEXTURES_2D
                result.add((section, spec.texture_id & 0x7FFF), f"Ground zipper header {definition.header_id}", levels)
    for index in range(source.count(AssetType.LEVEL_MODELS)):
        model = load_level_model(source, index)
        levels = model_levels.get(index, set())
        for slot, info in enumerate(model.textures):
            result.add((AssetType.TEXTURES_3D, info.texture_id), f"Geometry {index}, slot {slot}", levels)
        if model.raw_data:
            sprite_id = struct.unpack_from(">i", model.raw_data, 0x20)[0]
            result.add((AssetType.SPRITES, sprite_id), f"Geometry {index} minimap", levels)
    for index in range(source.count(AssetType.OBJECT_MODELS)):
        raw = source.read_asset(AssetType.OBJECT_MODELS, index, decompress=True)
        if len(raw) < 0x58:
            raise ValueError("Truncated object model image references")
        pointer, count = struct.unpack_from(">I", raw)[0], struct.unpack_from(">h", raw, 0x22)[0]
        if count < 0 or (count and pointer < 0x58) or pointer + count * 8 > len(raw):
            raise ValueError("Object model image references exceed the asset")
        for slot in range(count):
            texture_id = struct.unpack_from(">I", raw, pointer + slot * 8)[0]
            result.add((AssetType.TEXTURES_3D, texture_id), f"Object model {index}, slot {slot}", object_levels.get(index, set()))
    for index in range(source.count(AssetType.SPRITES)):
        sprite = load_sprite(source, index)
        levels = result.levels.get((AssetType.SPRITES, index), set())
        for frame in range(sprite.frame_count):
            for texture_id in sprite.texture_ids(frame):
                result.add((AssetType.TEXTURES_2D, texture_id), f"Sprite {index}, frame {frame}", levels)
    return result
