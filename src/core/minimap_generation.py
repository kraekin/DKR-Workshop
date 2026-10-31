"""Rasterize existing track faces into a fixed sprite and fit verified HUD markers.

Projection: local game_ui.c:minimap_marker_pos; pixel extents: sprite_init_frame.
Only existing minimap fields and fixed-layout texture pixels are written.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw

from src.core.image_assets import sprite_canvas, texture_from_raw
from src.core.level_model import LevelModel
from src.core.minimap import MinimapSettings, edit_minimap, load_minimap_tiles
from src.core.rom import AssetType

if TYPE_CHECKING:
    from src.core.editing import EditSession


@dataclass(frozen=True)
class MinimapGenerationOptions:
    surfaces: tuple[int, ...] | None = (0,)
    rotation: int = 0
    padding: int = 3
    minimum_up: float = 0.3


@dataclass(frozen=True)
class GeneratedMinimap:
    model_id: int
    sprite_id: int
    pixels: np.ndarray
    settings: MinimapSettings
    changes: tuple[tuple[tuple[AssetType, int], bytes, bytes], ...]
    face_count: int
    shared_uses: tuple[str, ...]


def minimap_faces(model: LevelModel, options: MinimapGenerationOptions) -> np.ndarray:
    if (options.rotation not in (0, 90, 180, 270) or type(options.padding) is not int
            or options.padding < 0 or not math.isfinite(options.minimum_up)
            or not 0 <= options.minimum_up <= 1):
        raise ValueError("Choose a quarter-turn rotation, nonnegative padding and valid slope limit")
    faces: list[np.ndarray] = []
    for segment in model.segments:
        for batch, end in zip(segment.batches, (*segment.batches[1:], segment.terminal_batch)):
            if batch.hidden or batch.flags & 0x200:
                continue
            surface = model.textures[batch.texture_index].surface_type if batch.texture_index != 255 else 0
            if options.surfaces is not None and surface not in options.surfaces:
                continue
            triangles = segment.vertices[segment.indices[batch.faces_offset:end.faces_offset]].astype(np.float64)
            normal = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            length = np.linalg.norm(normal, axis=1)
            selected = (length > 1e-8) & (np.abs(normal[:, 1]) > 1e-8) & (np.abs(normal[:, 1]) >= options.minimum_up * length)
            faces.extend(triangles[selected])
    if not faces:
        raise ValueError("No suitable faces: select other surfaces or allow steeper slopes")
    return np.asarray(faces)


def rasterize_minimap(model: LevelModel, triangles: np.ndarray, canvas_size: tuple[int, int],
                      tile_origin: tuple[int, int], anchor: tuple[int, int],
                      options: MinimapGenerationOptions) -> tuple[np.ndarray, dict[str, int | float]]:
    width, height = canvas_size
    if not 2 <= width <= 1024 or not 2 <= height <= 1024 or min(width, height) - 1 <= 2 * options.padding:
        raise ValueError("Sprite canvas is too small for the chosen padding")
    if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not len(triangles) or not np.isfinite(triangles).all():
        raise ValueError("Minimap geometry needs finite triangles")
    settings = MinimapSettings.from_bytes(model.raw_data)
    bounds = settings.bounds
    if bounds[1] <= bounds[0] or bounds[5] <= bounds[4]:
        raise ValueError("Minimap needs nonzero model X/Z bounds")
    # Retain the game's integer degrees-to-angle conversion, even for 90 degrees.
    angle = ((options.rotation * 65535) // 360 & 65535) * math.tau / 65536
    cosine, sine = math.cos(angle), math.sin(angle)
    rotation = np.array(((cosine, sine), (-sine, cosine)))
    coordinates = (triangles[:, :, (0, 2)] - (bounds[0], bounds[4])) @ rotation
    lower, upper = coordinates.min(axis=(0, 1)), coordinates.max(axis=(0, 1))
    span = upper - lower
    if np.any(span < 1e-6):
        raise ValueError("Selected geometry needs nonzero projected width and height")
    density = float(np.min((np.array((width, height)) - 1 - 2 * options.padding) / span))
    translate = (np.array((width, height)) - 1 - span * density) / 2 - lower * density
    offset_x = round(tile_origin[0] + translate[0])
    offset_y = round(-tile_origin[1] - 1 - translate[1])
    scale = density * (bounds[5] - bounds[4]) / 60
    changes = dict(rotation=options.rotation, scale_x=scale, scale_y=scale,
                   adv1_x=offset_x, adv1_y=offset_y,
                   adv2_x=anchor[0] - offset_x, adv2_y=offset_y,
                   red=255, green=255, blue=255)
    # Rasterize at the actual stored float32 scale and integer offsets, rather
    # than a different ideal fit, so artwork and marker projection coincide.
    stored_density = float(np.float32(scale)) * 60 / (bounds[5] - bounds[4])
    points = coordinates * stored_density + (offset_x - tile_origin[0], -offset_y - tile_origin[1] - 1)
    image = Image.new("L", (width * 4, height * 4))
    draw = ImageDraw.Draw(image)
    for face in points:
        draw.polygon([tuple(p * 4) for p in face], fill=255)
    alpha = np.array(image.resize((width, height), Image.Resampling.LANCZOS), np.uint8)
    pixels = np.full((height, width, 4), 255, np.uint8)
    pixels[:, :, 3] = alpha
    pixels[alpha == 0] = 0
    return pixels, changes


def generate_minimap(session: EditSession, model_id: int, options: MinimapGenerationOptions,
                     sprite_id: int | None = None) -> GeneratedMinimap:
    model = session.track_model(model_id)
    sprite_id = int(MinimapSettings.from_bytes(model.raw_data).values["sprite"]) if sprite_id is None else sprite_id
    canvas = sprite_canvas(session.asset_source, sprite_id)
    if canvas.layout != "Assembled sprite pixels":
        raise ValueError("This sprite has overlapping tiles; choose a minimap sprite with an assembled layout")
    sprite, tiles = load_minimap_tiles(session.asset_source, sprite_id)
    origin = (round(min(t.left for t in tiles) + sprite.anchor[0]),
              round(sprite.anchor[1] - max(t.top for t in tiles) - 1))
    triangles = minimap_faces(model, options)
    pixels, changes = rasterize_minimap(model, triangles, (canvas.pixels.shape[1], canvas.pixels.shape[0]),
                                        origin, sprite.anchor, options)
    covered = np.zeros(pixels.shape[:2], bool)
    for _, x, y, width, height in canvas.tiles:
        covered[y:y + height, x:x + width] = True
    if np.any(pixels[:, :, 3][~covered] > 8):
        raise ValueError("Selected geometry crosses gaps in this sprite's tile layout; choose a solid minimap canvas")
    pixels[~covered] = canvas.pixels[~covered]
    changes["sprite"] = sprite_id
    updated = edit_minimap(model.raw_data, changes, session.minimap_references)
    updates = session.image_updates(AssetType.SPRITES, sprite_id, 0, pixels)
    updates[AssetType.LEVEL_MODELS, model_id] = updated
    # Show the quantized stored pixels, including IA/I/RGBA format restrictions.
    decoded = np.zeros_like(pixels)
    for tile, x, y, width, height in canvas.tiles:
        raw = updates[AssetType.TEXTURES_2D, tile]
        decoded[y:y + height, x:x + width] = texture_from_raw(raw, tile, session.rom.section(AssetType.EMPTY_14)).frames[0].pixels
    uses = set()
    for key in updates:
        uses.update(session.image_uses.direct.get(key, ()))
        uses.update(session.image_uses.levels.get(key, ()))
    return GeneratedMinimap(model_id, sprite_id, decoded, MinimapSettings.from_bytes(updated),
        tuple((key, session.current_asset(*key), raw) for key, raw in sorted(updates.items())),
        len(triangles), tuple(sorted(uses)))


def apply_generated_minimap(session: EditSession, plan: GeneratedMinimap) -> bool:
    if any(session.current_asset(*key) != before for key, before, _ in plan.changes):
        raise ValueError("Minimap source changed after preview; generate a fresh preview")
    return session._replace_assets({key: after for key, _, after in plan.changes}, "Generate minimap artwork and alignment")
