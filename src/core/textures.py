"""N64 textures verified against textures_sprites.c and extractTexture.cpp.

Arrays retain top-to-bottom N64 rows. GL uploads unchanged rows and uses raw V;
OBJ writes 1-V against the same top-to-bottom PNG image.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
import math
import struct

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from src.core.compression import decompress_rare
from src.core.level_model import LevelModel
from src.core.objects import LevelObject
from src.core.rom import AssetError, AssetType, DecompAssets, RomImage, read_json


class TextureError(AssetError):
    """Invalid header, frame range, pixel data or palette reference."""


class TextureFormat(IntEnum):
    RGBA32 = 0
    RGBA16 = 1
    I8 = 2
    I4 = 3
    IA16 = 4
    IA8 = 5
    IA4 = 6
    CI4 = 7
    CI8 = 8


BITS: dict[TextureFormat, int] = dict(zip(TextureFormat, (32, 16, 8, 4, 16, 8, 4, 4, 8)))
Pixels = NDArray[np.uint8]


def image_size(width: int, height: int, format: TextureFormat) -> int:
    if not 1 <= width <= 255 or not 1 <= height <= 255:
        raise TextureError("Texture dimensions must be in 1..255")
    return (width * height * BITS[format] + 7) // 8


def deinterlace(data: bytes, width: int, height: int, format: TextureFormat) -> bytes:
    """Undo odd-row swaps: 8-byte halves for RGBA32, 4-byte otherwise.

    Partial groups stay untouched, matching imageHelper.cpp:191.
    """
    size = image_size(width, height, format)
    if len(data) != size:
        raise TextureError("Incorrect interlaced pixel byte count")
    row_bytes = width * BITS[format] // 8
    if width * BITS[format] % 8:
        raise TextureError("Interlaced rows must contain a whole number of bytes")
    half = 8 if format == TextureFormat.RGBA32 else 4
    output = bytearray(data)
    for row in range(1, height, 2):
        for column in range(row_bytes // (half * 2)):
            start = row * row_bytes + column * half * 2
            output[start:start + half * 2] = data[start + half:start + half * 2] + data[start:start + half]
    return bytes(output)


def decode_pixels(data: bytes, width: int, height: int, format: TextureFormat | int,
                  *, palette: bytes | None = None, interlaced: bool = False) -> Pixels:
    """Nine formats to RGBA8888; supplied CI palettes are BE RGBA5551.

    CI8 supports 256 colors; DKR supplies 64. I formats have opaque alpha,
    matching the local extraction utility. IA4 uses exact full-range scaling.
    """
    try:
        format = TextureFormat(format)
    except ValueError as error:
        raise TextureError(f"Unknown N64 texture format {format}") from error
    size = image_size(width, height, format)
    if len(data) != size:
        raise TextureError(f"Expected {size} pixel bytes; received {len(data)}")
    if interlaced:
        data = deinterlace(data, width, height, format)
    raw = np.frombuffer(data, dtype=np.uint8)
    count = width * height
    values = np.column_stack((raw >> 4, raw & 15)).reshape(-1)[:count] if BITS[format] == 4 else raw
    out = np.full((count, 4), 255, dtype=np.uint8)
    if format == TextureFormat.RGBA32:
        out[:] = raw.reshape(count, 4)
    elif format == TextureFormat.RGBA16:
        words = np.frombuffer(data, dtype=">u2").astype(np.uint32)
        for channel, shift in enumerate((11, 6, 1)):
            out[:, channel] = ((words >> shift) & 31) * 255 // 31
        out[:, 3] = (words & 1) * 255
    elif format in (TextureFormat.CI4, TextureFormat.CI8):
        limit = 16 if format == TextureFormat.CI4 else 256
        if palette is None or len(palette) % 2 or not 2 <= len(palette) <= limit * 2:
            raise TextureError("CI texture requires a valid RGBA16 palette")
        if int(values.max()) >= len(palette) // 2:
            raise TextureError("CI pixel index exceeds the supplied palette")
        words = np.frombuffer(palette, dtype=">u2").astype(np.uint32)
        colors = np.column_stack(tuple(((words >> shift) & 31) * 255 // 31 for shift in (11, 6, 1))
                                 + ((words & 1) * 255,)).astype(np.uint8)
        out[:] = colors[values]
    else:
        if format == TextureFormat.IA16:
            intensity, alpha = raw[::2], raw[1::2]
        elif format == TextureFormat.IA8:
            intensity, alpha = (raw >> 4) * 17, (raw & 15) * 17
        elif format == TextureFormat.IA4:
            intensity = (values >> 1).astype(np.uint16) * 255 // 7
            alpha = (values & 1) * 255
        else:
            intensity = values * 17 if format == TextureFormat.I4 else values
            alpha = np.full(count, 255, dtype=np.uint8)
        out[:, :3] = intensity[:, None]
        out[:, 3] = alpha
    result = out.reshape(height, width, 4)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class TextureHeader:
    width: int
    height: int
    format: TextureFormat
    render_mode: int
    flags: int
    palette_offset: int
    frame_count: int
    frame_advance: int
    frame_size: int
    compressed: bool
    raw: bytes

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> TextureHeader:
        if offset < 0 or offset + 32 > len(data):
            raise TextureError("Truncated 0x20-byte TextureHeader")
        raw = data[offset:offset + 32]
        try:
            format = TextureFormat(raw[2] & 15)
        except ValueError as error:
            raise TextureError("Unknown TextureHeader format") from error
        image_size(raw[0], raw[1], format)
        if raw[18] == 0 or raw[2] >> 4 > 3:
            raise TextureError("Invalid texture frame count or render mode")
        flags, palette = struct.unpack_from(">Hh", raw, 6)
        advance, size = struct.unpack_from(">Hh", raw, 20)
        return cls(raw[0], raw[1], format, raw[2] >> 4, flags, palette,
                   raw[18], advance, size, bool(raw[29]), raw)

    @property
    def clamp_u(self) -> bool:
        return bool(self.flags & 0x40) or self.width & (self.width - 1) != 0

    @property
    def clamp_v(self) -> bool:
        return bool(self.flags & 0x80) or self.height & (self.height - 1) != 0


@dataclass(frozen=True)
class TextureFrame:
    header: TextureHeader
    pixels: Pixels

    def to_image(self) -> Image.Image:
        return Image.fromarray(self.pixels)


@dataclass(frozen=True)
class Texture:
    texture_id: int
    frames: tuple[TextureFrame, ...]

    def frame_index(self, batch_offset: int) -> int:
        """tracks.c texOffset << 14 then material_set >> 16; static snapshot."""
        return batch_offset // 4 if 0 <= batch_offset < len(self.frames) * 4 else 0

    @classmethod
    def from_bytes(cls, data: bytes, *, texture_id: int = 0, palettes: bytes = b"") -> Texture:
        outer = TextureHeader.from_bytes(data)
        decoded = decompress_rare(data[32:]) if outer.compressed else data
        frames: list[TextureFrame] = []
        offset = 0
        shared_palette: bytes | None = None
        for index in range(outer.frame_count):
            header = TextureHeader.from_bytes(decoded, offset)
            size = image_size(header.width, header.height, header.format)
            end = offset + 32 + size
            if end > len(decoded):
                raise TextureError("Texture frame pixels extend beyond the asset")
            if header.frame_size and header.frame_size < 32 + size:
                raise TextureError("Invalid texture frame size")
            if index == 0 and header.format in (TextureFormat.CI4, TextureFormat.CI8):
                length = 32 if header.format == TextureFormat.CI4 else 128
                start = header.palette_offset
                if start < 0 or start + length > len(palettes):
                    raise TextureError("CI palette range is outside section 14")
                shared_palette = palettes[start:start + length]
            pixels = decode_pixels(decoded[offset + 32:end], header.width, header.height, header.format,
                                   palette=shared_palette, interlaced=bool(header.flags & 0x400))
            frames.append(TextureFrame(header, pixels))
            if index + 1 < outer.frame_count:
                if header.frame_size < 32 + size or offset + header.frame_size > len(decoded):
                    raise TextureError("Invalid animated texture frame stride")
                offset += header.frame_size
        return cls(texture_id, tuple(frames))


def load_texture(source: RomImage | DecompAssets, texture_id: int,
                 *, asset_type: AssetType = AssetType.TEXTURES_3D) -> Texture:
    if asset_type not in (AssetType.TEXTURES_3D,AssetType.TEXTURES_2D):
        raise TextureError('Texture section must be 2D or 3D')
    if isinstance(source, RomImage):
        return Texture.from_bytes(source.read_asset(asset_type, texture_id),
                                  texture_id=texture_id, palettes=source.section(AssetType.EMPTY_14))
    path = source.entry_path(asset_type, texture_id)
    if path.suffix.casefold() != ".json":
        return Texture.from_bytes(path.read_bytes(), texture_id=texture_id)
    metadata = read_json(path)
    if "raw" in metadata:
        return Texture.from_bytes(source._path(path.parent, metadata["raw"]).read_bytes(), texture_id=texture_id)
    try:
        format = TextureFormat[metadata["format"]]
        images = metadata["images"]
        if not isinstance(images, list) or not 1 <= len(images) <= 255:
            raise TextureError("Texture JSON needs 1..255 images")
        flags = metadata.get("flags", {})
        if not isinstance(flags, dict) or any(flags.get(key, "Wrap") not in ("Wrap", "Clamp") for key in ("wrap-s", "wrap-t")):
            raise TextureError("Texture flags must use verified Wrap/Clamp modes")
        mode = ("TRANSPARENT", "OPAQUE", "TRANSPARENT_2", "OPAQUE_2").index(metadata.get("render-mode", "OPAQUE"))
        frames: list[TextureFrame] = []
        advance_value = float(metadata.get("frame-advance-delay", 0)) * 60
        if not math.isfinite(advance_value) or not 0 <= advance_value <= 65535:
            raise TextureError("Invalid texture frame advance")
        for filename in images:
            with Image.open(source._path(path.parent, filename)) as image:
                if not 1 <= image.width <= 255 or not 1 <= image.height <= 255:
                    raise TextureError("Extracted texture dimensions exceed 1..255")
                pixels = np.array(image.convert("RGBA"), dtype=np.uint8)
            if metadata.get("flipped-image", False):
                pixels = np.ascontiguousarray(pixels[::-1])
            pixels.setflags(write=False)
            raw = bytearray(32)
            raw[0:3] = bytes((pixels.shape[1], pixels.shape[0], mode * 16 + format))
            raw[18] = len(images)
            try:
                raw[3:5] = struct.pack('>bb',metadata.get('sprite-x',0),metadata.get('sprite-y',0))
            except (struct.error,TypeError) as error:
                raise TextureError('Texture sprite offsets must be signed bytes') from error
            bits = 0x40 if flags.get("wrap-s", "Wrap") == "Clamp" else 0
            bits |= 0x80 if flags.get("wrap-t", "Wrap") == "Clamp" else 0
            bits |= (1 if flags.get("anti-aliased") else 0) | (4 if flags.get("semi-transparent") else 0) | (16 if flags.get("cutout") else 0)
            struct.pack_into(">H", raw, 6, bits)
            struct.pack_into(">H", raw, 20, round(advance_value))
            frames.append(TextureFrame(TextureHeader.from_bytes(bytes(raw)), pixels))
        return Texture(texture_id, tuple(frames))
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise TextureError(f"Invalid extracted texture {path.name}: {error}") from error


def load_model_textures(source: RomImage | DecompAssets, model: LevelModel,
                        cache: dict[int, Texture] | None = None) -> dict[int, Texture]:
    result: dict[int, Texture] = {}
    for info in model.textures:
        if cache is not None and info.texture_id in cache:
            texture = cache[info.texture_id]
        else:
            texture = load_texture(source, info.texture_id)
            if cache is not None:
                cache[info.texture_id] = texture
        result[info.texture_id] = texture
    return result


def normalize_uvs(uvs: NDArray, width: int, height: int, *, obj: bool = False) -> NDArray[np.float32]:
    if width <= 0 or height <= 0 or uvs.shape[-1] != 2:
        raise TextureError("Invalid UV dimensions")
    result = np.asarray(uvs, dtype=np.float32) / np.array([32 * width, 32 * height], dtype=np.float32)
    if obj:
        result[..., 1] = 1.0 - result[..., 1]
    return np.ascontiguousarray(result)


def model_uvs(model: LevelModel, textures: Mapping[int, Texture], *, obj: bool = False) -> NDArray[np.float32]:
    output = np.zeros((model.triangle_count, 3, 2), dtype=np.float32)
    for segment in model.segments:
        batches = (*segment.batches, segment.terminal_batch)
        for batch, following in zip(batches, batches[1:]):
            if batch.texture_index == 255:
                continue
            texture = textures[model.textures[batch.texture_index].texture_id]
            header = texture.frames[texture.frame_index(batch.texture_offset)].header
            first, end = batch.faces_offset, following.faces_offset
            output[segment.face_base + first:segment.face_base + end] = normalize_uvs(
                segment.uvs[first:end], header.width, header.height, obj=obj)
    return output

@dataclass(frozen=True)
class SpriteAsset:
    sprite_id: int
    base_texture_id: int
    anchor: tuple[int,int]
    frame_offsets: tuple[int,...]
    raw_data: bytes | None = None

    @property
    def frame_count(self) -> int:
        return len(self.frame_offsets)-1

    @classmethod
    def from_bytes(cls, data: bytes, *, sprite_id: int = 0) -> SpriteAsset:
        if len(data)<14:
            raise TextureError('Truncated 12-byte sprite header/frame offsets')
        base,count,x,y = struct.unpack_from('>4h',data)
        if base<0 or count<1 or 13+count>len(data):
            raise TextureError('Invalid sprite texture base or frame count')
        offsets=tuple(data[12:13+count])
        if offsets[0]!=0 or any(a>b for a,b in zip(offsets,offsets[1:])):
            raise TextureError('Sprite frame tile offsets must start at zero and increase')
        return cls(sprite_id,base,(x,y),offsets,data)

    def texture_ids(self, frame: int = 0) -> tuple[int,...]:
        if not 0<=frame<self.frame_count:
            raise TextureError('Sprite frame index is out of bounds')
        return tuple(range(self.base_texture_id+self.frame_offsets[frame],self.base_texture_id+self.frame_offsets[frame+1]))


def load_sprite(source: RomImage | DecompAssets, sprite_id: int) -> SpriteAsset:
    if isinstance(source,DecompAssets):
        path=source.entry_path(AssetType.SPRITES,sprite_id)
        document=read_json(path) if path.suffix.casefold()=='.json' else {}
        if document and 'raw' not in document:
            counts=document.get('frame-tex-count')
            if document.get('type')!='Sprite' or not isinstance(counts,list) or not 1<=len(counts)<=32767:
                raise TextureError('Invalid Sprite JSON frame-tex-count')
            if any(type(count) is not int or count<0 for count in counts) or sum(counts)>255:
                raise TextureError('Invalid sprite frame tile counts')
            anchor=(document.get('unk4',0),document.get('unk6',0))
            if any(type(value) is not int or not -32768<=value<=32767 for value in anchor):
                raise TextureError('Sprite anchors must be signed halfwords')
            base=source.resolve_id(AssetType.TEXTURES_2D,document.get('start-texture'))
            sprite=SpriteAsset(sprite_id,base,anchor,tuple(int(v) for v in np.cumsum((0,*counts))))
        else:
            sprite=SpriteAsset.from_bytes(source.read_asset(AssetType.SPRITES,sprite_id),sprite_id=sprite_id)
    else:
        sprite=SpriteAsset.from_bytes(source.read_asset(AssetType.SPRITES,sprite_id),sprite_id=sprite_id)
    if sprite.base_texture_id<0 or sprite.base_texture_id+sprite.frame_offsets[-1]>source.count(AssetType.TEXTURES_2D):
        raise TextureError('Sprite texture range exceeds the 2D texture table')
    return sprite


@dataclass(frozen=True)
class SpriteTile:
    texture_id: int
    frame: TextureFrame
    left: float
    right: float
    top: float
    bottom: float


@dataclass(frozen=True)
class SpriteInstance:
    object_index: int
    sprite_id: int
    position: tuple[float,float,float]
    scale: float
    tiles: tuple[SpriteTile,...]
    frames: tuple[tuple[SpriteTile,...],...] = ()
    frame_speed: float = 0.0  # normalized 0..255 frame counter per 60 Hz tick
    initial_frame: int = 0
    upright: bool = False  # Editor scenery preview; not a serialized game flag.

    def tiles_at(self, seconds: float) -> tuple[SpriteTile,...]:
        return self.frames[self.frame_at(seconds)] if self.frames else self.tiles

    def frame_at(self, seconds: float) -> int:
        return (((self.initial_frame+int(seconds*60*self.frame_speed)) & 255)*len(self.frames)) >> 8 if self.frames else 0

    @property
    def local_bounds(self) -> tuple[tuple[float,float],tuple[float,float]]:
        if not self.tiles:return ((0.,0.),(0.,0.))
        return ((min(tile.left for tile in self.tiles)*self.scale,min(tile.bottom for tile in self.tiles)*self.scale),
                (max(tile.right for tile in self.tiles)*self.scale,max(tile.top for tile in self.tiles)*self.scale))


def sprite_tiles(sprite: SpriteAsset, textures: Mapping[int,Texture], frame: int = 0) -> tuple[SpriteTile,...]:
    """sprite_init_frame: posX-anchorX, anchorY-posY, width/height minus 1."""
    tiles: list[SpriteTile]=[]
    for texture_id in sprite.texture_ids(frame):
        tile=textures[texture_id].frames[0]
        pos_x,pos_y=struct.unpack_from('>bb',tile.header.raw,3)
        x=pos_x-sprite.anchor[0];y=sprite.anchor[1]-pos_y
        tiles.append(SpriteTile(texture_id,tile,float(x),float(x+tile.header.width-1),float(y-1),float(y-tile.header.height)))
    return tuple(tiles)


# Physical billboard behaviors verified in object_functions.c. Logic helpers
# can reference editor-icon sprites, but the game marks those invisible.
WORLD_SPRITE_BEHAVIORS: frozenset[int]=frozenset((2,17,28,32,36,77,88,110,76))


def load_level_sprites(source: RomImage | DecompAssets, objects: tuple[LevelObject,...],
                       sprite_cache: dict[int,SpriteAsset] | None = None,
                       texture_cache: dict[int,Texture] | None = None) -> tuple[SpriteInstance,...]:
    sprite_cache = sprite_cache if sprite_cache is not None else {}
    texture_cache = texture_cache if texture_cache is not None else {}
    result: list[SpriteInstance]=[]
    for index,obj in enumerate(objects):
        definition=obj.definition;behavior=definition.behavior_id
        if definition.model_type!=1 or behavior not in WORLD_SPRITE_BEHAVIORS:
            continue
        if not definition.model_ids:
            raise TextureError(f'Billboard object {definition.name} has no sprite model IDs')
        selection=obj.value('balloonType',0) if behavior==17 else obj.value('modelIndex',0)
        if isinstance(selection,str) and behavior==17:
            labels=('BALLOON_TYPE_BOOST','BALLOON_TYPE_MISSILE','BALLOON_TYPE_TRAP','BALLOON_TYPE_SHIELD','BALLOON_TYPE_MAGNET')
            selection=labels.index(selection) if selection in labels else 0
        if type(selection) is not int or not 0<=selection<len(definition.model_ids):selection=0
        sprite_id=definition.model_ids[selection]
        if sprite_id not in sprite_cache:sprite_cache[sprite_id]=load_sprite(source,sprite_id)
        sprite=sprite_cache[sprite_id]
        speed = float(obj.value('animSpeed',0)) if behavior == 28 else (8.0 if behavior in (32,36,76,88,110) else 0.0)
        animated = sprite.frame_count > 1 and speed != 0
        texture_ids = range(sprite.base_texture_id,sprite.base_texture_id+sprite.frame_offsets[-1]) if animated else sprite.texture_ids()
        for texture_id in texture_ids:
            if texture_id not in texture_cache:
                texture_cache[texture_id]=load_texture(source,texture_id,asset_type=AssetType.TEXTURES_2D)
        scale=definition.scale
        if behavior in (2,28):scale*=max(float(obj.value('radius',64)),10)/64
        elif behavior in (17,77):scale*=max(float(obj.value('scale',64)),10)/64
        frames = tuple(sprite_tiles(sprite,texture_cache,i) for i in range(sprite.frame_count)) if animated else ()
        result.append(SpriteInstance(index,sprite_id,obj.position,scale,sprite_tiles(sprite,texture_cache),frames,speed,
                                     upright=behavior==2))
    return tuple(result)
