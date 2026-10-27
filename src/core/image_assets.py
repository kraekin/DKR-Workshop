"""Fixed-layout image encoding, PNG interchange and sprite anchors.

Sources: n64graphics.c:16,207–317,506; imageHelper.cpp:191;
buildTexture.cpp; structs.h:102/156; textures_sprites.c:1306/1620.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import zlib
import numpy as np
from PIL import Image, PngImagePlugin

from src.core.compression import decompress_rare
from src.core.rom import AssetType, RomImage, DecompAssets, read_json
from src.core.textures import (Texture, TextureHeader, TextureFormat, SpriteAsset,
    TextureError, Pixels, BITS, image_size, decode_pixels, deinterlace, load_sprite, load_texture)

TEXTURE_SECTIONS = frozenset((AssetType.TEXTURES_3D, AssetType.TEXTURES_2D))
IMAGE_SECTIONS = TEXTURE_SECTIONS | {AssetType.SPRITES}


def encode_pixels(pixels: Pixels, format: TextureFormat, *, palette: bytes | None = None,
                  interlaced: bool = False) -> bytes:
    """Quantize using the local builder's integer rules; existing CI palette only."""
    p = np.asarray(pixels)
    if p.dtype != np.uint8 or p.ndim != 3 or p.shape[2] != 4:
        raise TextureError("Image must contain uint8 RGBA pixels")
    height, width = p.shape[:2]
    image_size(width, height, format)
    flat = p.reshape(-1, 4).astype(np.uint32)
    if format == TextureFormat.RGBA32:
        raw = p.tobytes()
    elif format == TextureFormat.RGBA16:
        rgb = ((flat[:, :3] + 4) * 31 // 255)
        words = (rgb[:, 0] << 11) | (rgb[:, 1] << 6) | (rgb[:, 2] << 1) | (flat[:, 3] != 0)
        raw = words.astype(">u2").tobytes()
    else:
        intensity = (flat[:, :3].sum(axis=1) + 1) // 3
        if format == TextureFormat.IA16:
            values = np.column_stack((intensity, flat[:, 3])).reshape(-1)
        elif format == TextureFormat.IA8:
            values = ((intensity // 17) << 4) | (flat[:, 3] // 17)
        elif format == TextureFormat.IA4:
            values = ((intensity // 36) << 1) | (flat[:, 3] != 0)
        elif format in (TextureFormat.I8, TextureFormat.I4):
            values = intensity if format == TextureFormat.I8 else intensity // 17
        elif format in (TextureFormat.CI4, TextureFormat.CI8):
            count = 16 if format == TextureFormat.CI4 else 64
            if palette is None or len(palette) % 2 or not 2 <= len(palette) <= count * 2:
                raise TextureError("Import requires the existing DKR palette; palette replacement is not enabled")
            colors = decode_pixels(bytes(range(len(palette) // 2)), len(palette) // 2, 1, TextureFormat.CI8, palette=palette).reshape(-1, 4).astype(np.int32)
            # Chunk to bound intermediate memory for larger images.
            values = np.concatenate([np.argmin(np.sum((chunk[:, None, :].astype(np.int32) - colors) ** 2, axis=2), axis=1)
                                     for chunk in np.array_split(flat, max(1, len(flat) // 1024))])
        else:
            raise TextureError("Unsupported image format")
        values = values.astype(np.uint8)
        if BITS[format] == 4:
            if len(values) % 2:
                values = np.append(values, np.uint8(0))
            raw = ((values[::2] << 4) | values[1::2]).tobytes()
        else:
            raw = values.tobytes()
    return deinterlace(raw, width, height, format) if interlaced else raw


def unpack_texture(data: bytes) -> bytes:
    """Canonical editable bytes: compressed outer header + inflated entry, or raw."""
    outer = TextureHeader.from_bytes(data)
    return data[:32] + decompress_rare(data[32:]) if outer.compressed else data


def pack_texture(raw: bytes) -> bytes:
    outer = TextureHeader.from_bytes(raw)
    if not outer.compressed:
        return raw
    decoded = raw[32:]
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    result = raw[:32] + struct.pack("<IB", len(decoded), 9) + compressor.compress(decoded) + compressor.flush()
    return result + bytes(-len(result) % 16)


@dataclass(frozen=True)
class FrameSpan:
    header: TextureHeader
    offset: int
    start: int
    end: int


def frame_spans(raw: bytes) -> tuple[FrameSpan, ...]:
    outer = TextureHeader.from_bytes(raw)
    offset = 32 if outer.compressed else 0
    result: list[FrameSpan] = []
    for index in range(outer.frame_count):
        header = TextureHeader.from_bytes(raw, offset)
        start = offset + 32
        end = start + image_size(header.width, header.height, header.format)
        if end > len(raw) or (header.frame_size and header.frame_size < end - offset):
            raise TextureError("Image frame exceeds its original byte span")
        result.append(FrameSpan(header, offset, start, end))
        if index + 1 < outer.frame_count:
            if header.frame_size < end - offset:
                raise TextureError("Animated image frame stride is invalid")
            offset += header.frame_size
    return tuple(result)


def texture_from_raw(raw: bytes, texture_id: int = 0, palettes: bytes = b"") -> Texture:
    # Decoder consumes the existing on-disk wrapping, not our editable container.
    return Texture.from_bytes(pack_texture(raw), texture_id=texture_id, palettes=palettes)


def _palette(span: FrameSpan, palettes: bytes) -> bytes | None:
    if span.header.format not in (TextureFormat.CI4, TextureFormat.CI8):
        return None
    size = 32 if span.header.format == TextureFormat.CI4 else 128
    offset = span.header.palette_offset
    if offset < 0 or offset + size > len(palettes):
        raise TextureError("Existing CI palette is outside section 14")
    return palettes[offset:offset + size]


def replace_frame(raw: bytes, frame: int, pixels: Pixels, *, palettes: bytes = b"") -> bytes:
    spans = frame_spans(raw)
    if type(frame) is not int or not 0 <= frame < len(spans):
        raise TextureError("Image frame is outside the existing sequence")
    span = spans[frame]
    h = span.header
    if pixels.dtype != np.uint8 or pixels.shape != (h.height, h.width, 4):
        raise TextureError(f"PNG must remain {h.width}×{h.height} RGBA; resizing is not enabled")
    old = decode_pixels(raw[span.start:span.end], h.width, h.height, h.format,
                        palette=_palette(spans[0], palettes), interlaced=bool(h.flags & 0x400))
    changed = np.any(pixels != old, axis=2).reshape(-1)
    if not np.any(changed):
        return raw
    encoded = encode_pixels(pixels, h.format, palette=_palette(spans[0], palettes))
    before = raw[span.start:span.end]
    if h.flags & 0x400:
        before = deinterlace(before, h.width, h.height, h.format)
    mask = np.zeros(len(encoded), np.uint8)
    if BITS[h.format] == 4:
        for i in np.flatnonzero(changed):
            mask[i // 2] |= 0xF0 if i % 2 == 0 else 0x0F
    else:
        mask[:] = np.repeat(changed, BITS[h.format] // 8) * 255
    merged = ((np.frombuffer(before, np.uint8) & ~mask) | (np.frombuffer(encoded, np.uint8) & mask)).tobytes()
    if h.flags & 0x400:
        merged = deinterlace(merged, h.width, h.height, h.format)
    return raw[:span.start] + merged + raw[span.end:]


def validate_texture_edit(original: bytes, updated: bytes, palettes: bytes = b"") -> None:
    if len(original) != len(updated):
        raise TextureError("Image edits must retain their full decoded length")
    mask = np.zeros(len(original), np.uint8)
    for span in frame_spans(original):
        mask[span.start:span.end] = 255
        # Preserve an unused final nibble in odd-sized 4-bit images.
        if BITS[span.header.format] == 4 and span.header.width * span.header.height % 2:
            mask[span.end - 1] = 0xF0
        mask[span.offset + 20:span.offset + 22] = 255
    if TextureHeader.from_bytes(original).compressed:
        mask[20:22] = 255
    if np.any((np.frombuffer(original, np.uint8) ^ np.frombuffer(updated, np.uint8)) & ~mask):
        raise TextureError("Image edit changes protected dimensions, format, counts, flags, layout or padding")
    frame_spans(updated)
    texture_from_raw(updated, palettes=palettes)


def edit_timing(raw: bytes, advance: int) -> bytes:
    if type(advance) is not int or not 0 <= advance <= 65535:
        raise TextureError("Texture timing must be an unsigned16 integer")
    spans = frame_spans(raw)
    if advance == spans[0].header.frame_advance:
        return raw  # Preserve any legacy per-frame/outer metadata on a no-op.
    out = bytearray(raw)
    for offset in {0, *(span.offset for span in spans)}:
        struct.pack_into(">H", out, offset + 20, advance)
    return bytes(out)


def edit_anchor(raw: bytes, x: int, y: int) -> bytes:
    SpriteAsset.from_bytes(raw)
    if any(type(v) is not int or not -32768 <= v <= 32767 for v in (x, y)):
        raise TextureError("Sprite anchors must be signed16 integers")
    out = bytearray(raw)
    struct.pack_into(">2h", out, 4, x, y)
    return bytes(out)


def validate_sprite_edit(original: bytes, updated: bytes) -> None:
    if len(original) != len(updated) or original[:4] != updated[:4] or original[8:] != updated[8:]:
        raise TextureError("Sprite edits only allow its existing signed anchor coordinates")
    SpriteAsset.from_bytes(updated)


@dataclass(frozen=True)
class SpriteCanvas:
    pixels: Pixels
    tiles: tuple[tuple[int, int, int, int, int], ...]  # texture ID, x,y,width,height
    layout: str


def sprite_canvas(source: RomImage | DecompAssets, sprite_id: int, frame: int = 0) -> SpriteCanvas:
    sprite = load_sprite(source, sprite_id)
    textures = [(index, load_texture(source, index, asset_type=AssetType.TEXTURES_2D).frames[0])
                for index in sprite.texture_ids(frame)]
    if not textures:
        raise TextureError("This sprite frame has no tiles to export/import")
    rects = [(index, *struct.unpack_from(">bb", tex.header.raw, 3), tex.header.width, tex.header.height) for index, tex in textures]
    overlap = any(max(a[1], b[1]) < min(a[1] + a[3], b[1] + b[3]) and max(a[2], b[2]) < min(a[2] + a[4], b[2] + b[4])
                  for i, a in enumerate(rects) for b in rects[i + 1:])
    if overlap:
        # Every texel stays editable, including pixels hidden by overlapping tiles.
        cursor = 0
        rects = []
        for index, tex in textures:
            rects.append((index, cursor, 0, tex.header.width, tex.header.height))
            cursor += tex.header.width
        layout = "Tile sheet (overlapping source tiles placed left to right)"
    else:
        left, top = min(r[1] for r in rects), min(r[2] for r in rects)
        rects = [(i, x - left, y - top, w, h) for i, x, y, w, h in rects]
        layout = "Assembled sprite pixels"
    width, height = max(r[1] + r[3] for r in rects), max(r[2] + r[4] for r in rects)
    pixels = np.zeros((height, width, 4), np.uint8)
    for (_, tex), (_, x, y, w, h) in zip(textures, rects):
        pixels[y:y + h, x:x + w] = tex.pixels
    return SpriteCanvas(pixels, tuple(rects), layout)


def split_sprite_png(canvas: SpriteCanvas, pixels: Pixels) -> dict[int, Pixels]:
    if pixels.dtype != np.uint8 or pixels.shape != canvas.pixels.shape:
        raise TextureError(f"Sprite PNG must remain {canvas.pixels.shape[1]}×{canvas.pixels.shape[0]}; keep its tile layout")
    covered = np.zeros(pixels.shape[:2], bool)
    result: dict[int, Pixels] = {}
    for index, x, y, w, h in canvas.tiles:
        covered[y:y + h, x:x + w] = True
        result[index] = pixels[y:y + h, x:x + w].copy()
    if np.any(np.any(pixels[~covered] != canvas.pixels[~covered], axis=1)):
        raise TextureError("PNG changes empty space outside the existing sprite tiles")
    return result


def png_flip_default(source: RomImage | DecompAssets, section: AssetType, index: int) -> bool:
    """Local extract config: 3D flip=true, 2D=false; JSON records overrides.

    This is an editing convention, not a TextureHeader flag or image heuristic.
    Canonical renderer/writer pixels always retain their original stored rows.
    """
    if section != AssetType.TEXTURES_3D:
        return False
    # Dedicated OBJ artwork already follows its PNG/OBJ UV convention. The
    # stock extractor's upright editing flip does not apply to these assets.
    if index in getattr(source,'dedicated_texture_ids',()):
        return False
    if isinstance(source, DecompAssets):
        path = source.entry_path(section, index)
        if path.suffix.casefold() == ".json":
            metadata = read_json(path)
            if "raw" not in metadata:
                value = metadata.get("flipped-image", False)
                if type(value) is not bool:
                    raise TextureError("Extracted flipped-image must be a boolean")
                return value
    return True


def png_rows(pixels: Pixels, *, flip_y: bool) -> Pixels:
    """Symmetric stored↔PNG row conversion; never mutate shared decoded arrays."""
    return np.ascontiguousarray(pixels[::-1] if flip_y else pixels)


def read_png(path: Path, expected_size: tuple[int, int], *,
             asset_type: AssetType | None = None, flip_y: bool = False) -> Pixels:
    with Image.open(path) as image:
        if image.format != "PNG" or image.size != expected_size or getattr(image, "n_frames", 1) != 1:
            raise TextureError(f"Choose one PNG frame at the original {expected_size[0]}×{expected_size[1]} size")
        if asset_type is not None and image.info.get("dkr-asset-section") == str(int(asset_type)):
            rows = image.info.get("dkr-png-rows")
            if rows is not None:
                if rows not in ("stored", "flip-y"):
                    raise TextureError("Unrecognized DKR PNG orientation metadata")
                flip_y = rows == "flip-y"
        return png_rows(np.array(image.convert("RGBA"), np.uint8), flip_y=flip_y)


def export_png(pixels: Pixels, path: Path, *, asset_type: AssetType | None = None,
               flip_y: bool = False) -> Path:
    if path.suffix.casefold() != ".png":
        raise TextureError("Image exports use .png")
    # Encode before touching an existing destination.
    import io
    import tempfile
    stream = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    if asset_type is not None:
        metadata.add_text("dkr-asset-section", str(int(asset_type)))
        metadata.add_text("dkr-png-rows", "flip-y" if flip_y else "stored")
    Image.fromarray(png_rows(pixels, flip_y=flip_y)).save(stream, format="PNG", pnginfo=metadata)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".dkr-png-", delete=False) as out:
            temporary = Path(out.name)
            out.write(stream.getvalue())
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
