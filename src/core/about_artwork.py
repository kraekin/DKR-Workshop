from __future__ import annotations

from dataclasses import dataclass
import struct

import numpy as np
from PIL import Image

from src.core.objects import load_object_database
from src.core.rom import AssetType, RomImage
from src.core.special_art import shadow_spec
from src.core.textures import Pixels, TextureError, load_sprite, load_texture


@dataclass(frozen=True)
class AboutArtwork:
    balloons: tuple[Pixels, ...]
    pop_frames: tuple[Pixels, ...]
    logo: Pixels
    background: Pixels
    sun: Pixels
    zipper: Pixels


def _pixels(image: Image.Image) -> Pixels:
    result = np.array(image, dtype=np.uint8)
    result.setflags(write=False)
    return result


def _compose(tiles: tuple[tuple[Pixels, int, int], ...],
             bounds: tuple[int, int, int, int] | None = None) -> Pixels:
    if bounds is None:
        if not tiles:
            raise TextureError('About artwork has no image tiles')
        bounds = (min(x for _, x, _ in tiles), min(y for _, _, y in tiles),
                  max(x + p.shape[1] for p, x, _ in tiles),
                  max(y + p.shape[0] for p, _, y in tiles))
    left, top, right, bottom = bounds
    if not 0 < right-left <= 2048 or not 0 < bottom-top <= 2048:
        raise TextureError('About artwork exceeds its canvas bounds')
    canvas = Image.new('RGBA', (right-left, bottom-top))
    for pixels, x, y in tiles:
        canvas.alpha_composite(Image.fromarray(pixels), (x-left, y-top))
    return _pixels(canvas)


def _sprite_frames(source: RomImage, sprite_id: int) -> tuple[Pixels, ...]:
    sprite = load_sprite(source, sprite_id)
    textures = {i: load_texture(source, i, asset_type=AssetType.TEXTURES_2D).frames[0]
                for i in range(sprite.base_texture_id, sprite.base_texture_id+sprite.frame_offsets[-1])}
    frames = tuple(tuple((textures[i].pixels, *struct.unpack_from('>bb', textures[i].header.raw, 3))
                         for i in sprite.texture_ids(frame)) for frame in range(sprite.frame_count))
    tiles = tuple(tile for frame in frames for tile in frame)
    if not tiles:
        raise TextureError('About sprite has no visible frames')
    bounds = (min(x for _, x, _ in tiles), min(y for _, _, y in tiles),
              max(x+p.shape[1] for p, x, _ in tiles), max(y+p.shape[0] for p, _, y in tiles))
    return tuple(_compose(frame, bounds) for frame in frames)


def _title(source: RomImage) -> Pixels:
    # menu.h TEXTURE_TITLE_SEGMENT_01..11 are menu IDs 0x50..0x5A.
    # menu.c sGameTitleTileOffsets spaces tiles by 15, including the trademark.
    table = source.section(AssetType.MENU_ELEMENT_IDS)
    if len(table) % 2 or len(table) < 0x5B*2:
        raise TextureError('Truncated About menu reference table')
    tiles: list[tuple[Pixels, int, int]] = []
    for index in range(11):
        reference = struct.unpack_from('>H', table, (0x50+index)*2)[0]
        if reference & 0xC000 != 0xC000:
            raise TextureError('About title reference is not a menu texture')
        frame = load_texture(source, reference & 0x3FFF, asset_type=AssetType.TEXTURES_2D).frames[0]
        tiles.append((frame.pixels, index*15, 0))
    return _compose(tuple(tiles))


def load_about_artwork(source: RomImage) -> AboutArtwork:
    database = load_object_database(source)
    definitions = {d.name: d for d in database.definitions}
    weapon = definitions.get('WeaponBalloon')
    gold = definitions.get('GoldenBalloon')
    ground = definitions.get('GroundZipper')
    if (weapon is None or weapon.model_type != 1 or len(weapon.model_ids) < 5 or
            gold is None or gold.model_type != 1 or not gold.model_ids or ground is None):
        raise TextureError('About artwork object references are unavailable')
    # Game enum: boost, missile, trap, shield, magnet. Retain the user's color order.
    balloon_ids = tuple(weapon.model_ids[i] for i in (1, 0, 3, 2, 4)) + (gold.model_ids[0],)
    balloons = tuple(_sprite_frames(source, i)[0] for i in balloon_ids)
    spec = shadow_spec(source, ground)
    if spec is None:
        raise TextureError('About ground zipper texture is unavailable')
    section = AssetType.TEXTURES_3D if spec.texture_id & 0x8000 else AssetType.TEXTURES_2D
    zipper = load_texture(source, spec.texture_id & 0x7FFF, asset_type=section).frames[0].pixels
    # us.v80 manifest: sprite176 weapon_balloon_pop; tex3D817 dome_blue_sky_island;
    # tex3D220 dome_sun_shining. Sky art is flipped for its flat presentation.
    background = load_texture(source, 817).frames[0].pixels[::-1].copy()
    background.setflags(write=False)
    sun = load_texture(source, 220).frames[0].pixels
    return AboutArtwork(balloons, _sprite_frames(source, 176), _title(source), background, sun, zipper)
