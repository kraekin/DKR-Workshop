"""Fixed minimap settings and HUD-relative projection, without Qt or OpenGL.

Sources: structs.h:737; game_ui.c:minimap_init/minimap_marker_pos;
camera.c:render_ortho_triangle_image; textures_sprites.c:sprite_init_frame.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import struct
import numpy as np

from src.core.level_model import LevelModel
from src.core.materials import TextureReference, validate_material_edit
from src.core.rom import AssetType, DecompAssets, RomImage
from src.core.textures import SpriteAsset, SpriteTile, load_sprite, load_texture, sprite_tiles


@dataclass(frozen=True)
class MinimapField:
    key: str
    label: str
    offset: int
    format: str

    @property
    def size(self) -> int:
        return struct.calcsize(self.format)

    def read(self, raw: bytes) -> int | float:
        return struct.unpack_from(self.format, raw, self.offset)[0]


MINIMAP_FIELDS = (
    MinimapField("sprite", "Map sprite ID", 0x20, ">i"),
    MinimapField("rotation", "Marker rotation (degrees)", 0x24, ">H"),
    MinimapField("scale_x", "Marker X scale", 0x28, ">f"),
    MinimapField("scale_y", "Marker Z scale", 0x2C, ">f"),
    MinimapField("adv1_x", "Adventure 1 X offset", 0x30, ">h"),
    MinimapField("adv1_y", "Adventure 1 Y offset", 0x32, ">h"),
    MinimapField("adv2_x", "Adventure 2 X offset", 0x34, ">h"),
    MinimapField("adv2_y", "Adventure 2 Y offset", 0x36, ">h"),
    # High byte @38 is not read by minimap_init; keep it protected.
    MinimapField("red", "Map tint red", 0x39, ">B"),
    MinimapField("green", "Map tint green", 0x3A, ">B"),
    MinimapField("blue", "Map tint blue", 0x3B, ">B"),
)
FIELD_BY_KEY = {field.key: field for field in MINIMAP_FIELDS}


def minimap_mask(length: int) -> np.ndarray:
    if length < 0x4C:
        raise ValueError("Truncated LevelModel minimap header")
    mask = np.zeros(length, np.uint8)
    for field in MINIMAP_FIELDS:
        mask[field.offset:field.offset + field.size] = 255
    return mask


def copy_minimap(target: bytes, source: bytes) -> bytes:
    """Copy just the writable minimap bytes, preserving every other byte."""
    if len(target) != len(source):
        raise ValueError("Minimap edits must retain the complete inflated model length")
    out = bytearray(target)
    for field in MINIMAP_FIELDS:
        out[field.offset:field.offset + field.size] = source[field.offset:field.offset + field.size]
    return bytes(out)


@dataclass(frozen=True)
class SpriteReference:
    sprite: SpriteAsset

    @property
    def sprite_id(self) -> int:
        return self.sprite.sprite_id

    @property
    def label(self) -> str:
        s = self.sprite
        return f"{s.sprite_id} · {len(s.texture_ids())} tiles · {s.frame_count} frames"


def sprite_references(source: RomImage | DecompAssets) -> tuple[SpriteReference, ...]:
    """Only existing, nonempty first frames accepted by the game's HUD path."""
    refs: list[SpriteReference] = []
    for index in range(source.count(AssetType.SPRITES)):
        sprite = load_sprite(source, index)
        if sprite.texture_ids():
            refs.append(SpriteReference(sprite))
    return tuple(refs)


@dataclass(frozen=True)
class MinimapSettings:
    values: Mapping[str, int | float]
    bounds: tuple[int, ...]  # lowerX, upperX, lowerY, upperY, lowerZ, upperZ

    @classmethod
    def from_bytes(cls, raw: bytes) -> MinimapSettings:
        if len(raw) < 0x4C:
            raise ValueError("Truncated LevelModel minimap header")
        return cls({field.key: field.read(raw) for field in MINIMAP_FIELDS}, struct.unpack_from(">6h", raw, 0x3C))

    @property
    def tint(self) -> tuple[int, int, int]:
        return tuple(int(self.values[key]) for key in ("red", "green", "blue"))


def validate_minimap_edit(original: bytes, updated: bytes, refs: Sequence[SpriteReference]) -> None:
    if len(original) != len(updated):
        raise ValueError("Minimap edits must retain the complete inflated model length")
    mask = minimap_mask(len(original))
    delta = np.frombuffer(original, np.uint8) ^ np.frombuffer(updated, np.uint8)
    if np.any(delta & ~mask):
        raise ValueError("Minimap edit changes protected model fields")
    before, after = MinimapSettings.from_bytes(original), MinimapSettings.from_bytes(updated)
    for field in MINIMAP_FIELDS:
        a, b = before.values[field.key], after.values[field.key]
        if a == b:
            continue
        if field.key == "sprite" and b not in {ref.sprite_id for ref in refs}:
            raise ValueError("Minimap sprite must reference an existing nonempty first frame")
        if field.format == ">f" and not math.isfinite(b):
            raise ValueError("Minimap scales must be finite float32 values")
    if original != updated and (after.bounds[1] <= after.bounds[0] or after.bounds[5] <= after.bounds[4]):
        raise ValueError("Minimap projection needs nonzero X and Z model bounds")


def edit_minimap(raw: bytes, changes: Mapping[str, int | float], refs: Sequence[SpriteReference]) -> bytes:
    MinimapSettings.from_bytes(raw)
    out = bytearray(raw)
    for key, value in changes.items():
        if key not in FIELD_BY_KEY:
            raise ValueError(f"Unsupported minimap field: {key}")
        field = FIELD_BY_KEY[key]
        if field.format == ">f":
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Minimap scales must be finite float32 values")
        elif type(value) is not int:
            raise ValueError("Minimap integer fields require an integer")
        try:
            struct.pack_into(field.format, out, field.offset, value)
        except (struct.error, OverflowError) as error:
            raise ValueError(f"{field.label}: value exceeds its stored format") from error
    result = bytes(out)
    validate_minimap_edit(raw, result, refs)
    return result


def validate_model_edit(original: bytes, updated: bytes, textures: Sequence[TextureReference],
                        sprites: Sequence[SpriteReference], *, allow_geometry: bool = False) -> LevelModel:
    """Union of the separately verified material and minimap writers."""
    materials = updated
    if allow_geometry:
        from src.core.geometry import validate_geometry, copy_geometry
        validate_geometry(original, updated)
        materials = copy_geometry(updated, original)
    validate_material_edit(original, copy_minimap(materials, original), textures)
    validate_minimap_edit(original, copy_minimap(original, updated), sprites)
    return LevelModel.from_bytes(updated)


def minimap_changes(original: bytes, updated: bytes) -> tuple[str, ...]:
    return tuple(f"Minimap {field.label}: {field.read(original)} → {field.read(updated)}"
                 for field in MINIMAP_FIELDS if field.read(original) != field.read(updated))


def project_markers(settings: MinimapSettings, xz: np.ndarray, anchor: tuple[int, int],
                    *, mirrored: bool = False) -> np.ndarray:
    """game_ui.c:3771, relative to gMinimapScreenX/Y. Positive Y points up.

    Keep the integer degrees→N64-angle conversion. Continuous trig approximates
    the game's sine lookup at subpixel precision; HUD layout/TV scaling excluded.
    Mirroring expects the original, unmirrored ROM coordinates (as in the editor).
    """
    points = np.asarray(xz, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.all(np.isfinite(points)):
        raise ValueError("Minimap points need finite X,Z pairs")
    lower_x, upper_x, _, _, lower_z, upper_z = settings.bounds
    a, b = upper_x - lower_x, upper_z - lower_z
    if a <= 0 or b <= 0:
        raise ValueError("Minimap projection needs nonzero X and Z model bounds")
    v = settings.values
    angle = ((int(v["rotation"]) * 65535) // 360 & 65535) * (math.tau / 65536)
    cosine, sine = math.cos(angle), math.sin(angle)
    scaled_x = 60 * (a / b) * float(v["scale_x"]) * (points[:, 0] - lower_x) / a
    scaled_y = -60 * float(v["scale_y"]) * (points[:, 1] - lower_z) / b
    rotated_x = scaled_x * cosine + scaled_y * sine
    rotated_y = scaled_x * sine - scaled_y * cosine
    prefix = "adv2" if mirrored else "adv1"
    result = np.column_stack((( -rotated_x if mirrored else rotated_x) + v[prefix + "_x"] - anchor[0],
                              v[prefix + "_y"] - rotated_y + anchor[1]))
    if not np.all(np.isfinite(result)):
        raise ValueError("Minimap projection exceeds preview precision")
    return result


def load_minimap_tiles(source: RomImage | DecompAssets, sprite_id: int) -> tuple[SpriteAsset, tuple[SpriteTile, ...]]:
    sprite = load_sprite(source, sprite_id)
    textures = {index: load_texture(source, index, asset_type=AssetType.TEXTURES_2D) for index in sprite.texture_ids()}
    return sprite, sprite_tiles(sprite, textures)


def tile_bounds(tile: SpriteTile, anchor: tuple[int, int], *, mirrored: bool = False) -> tuple[float, float, float, float]:
    """HUD-relative left,bottom,right,top; Adv2 yaw reflection plus anchor shift."""
    if mirrored:
        return -anchor[0] - tile.right, tile.bottom, -anchor[0] - tile.left, tile.top
    return tile.left, tile.bottom, tile.right, tile.top
