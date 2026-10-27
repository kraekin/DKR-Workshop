"""Bounded OBJ material sidecars and canonical dedicated static 3D textures.

Sources: local objModel.cpp:162–240, buildTexture.cpp:45–133,
structs.h:102–140, textures_sprites.c:378–405/455–583/1450–1605,
PR/gbi.h G_IM_SIZ_* and gDPLoadTextureBlock. No Qt/OpenGL dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
import shlex
import struct
from collections.abc import Mapping, Sequence

import numpy as np
from PIL import Image

from src.core.image_assets import encode_pixels
from src.core.level_model import LevelModel, TextureInfo
from src.core.materials import SURFACES, TextureReference
from src.core.textures import Texture, TextureFormat, TextureHeader, Pixels
from src.core.track_import import ImportError

MAX_CUSTOM_TEXTURES = 128  # Editor project bound, not a game-wide texture limit.
MAX_SIDECAR_BYTES = 1024 * 1024
MAX_PNG_BYTES = 16 * 1024 * 1024
MAX_PNG_PIXELS = 4096 * 4096
SIZES = (8, 16, 32, 64)
FORMATS = (TextureFormat.RGBA16, TextureFormat.RGBA32)
ALPHA_MODES = ('Opaque', 'Cutout', 'Blend')


@dataclass(frozen=True)
class TextureOptions:
    width: int = 32
    height: int = 32
    format: TextureFormat = TextureFormat.RGBA16
    alpha: str = 'Opaque'
    clamp_u: bool = False
    clamp_v: bool = False


@dataclass(frozen=True)
class ObjMaterial:
    name: str
    image: Path | None = None
    diffuse: tuple[float, float, float] = (1., 1., 1.)
    opacity: float = 1.
    clamp: bool = False
    problems: tuple[str, ...] = ()
    alpha_image: Path | None = None


def _text(path: Path) -> str:
    if path.stat().st_size > MAX_SIDECAR_BYTES:
        raise ImportError(f'Material sidecar exceeds 1 MiB: {path.name}')
    data = path.read_bytes()
    if len(data) > MAX_SIDECAR_BYTES:
        raise ImportError('Material sidecar exceeds 1 MiB')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ImportError(f'Material sidecar must be UTF-8: {path.name}') from error


def _tokens(value: str) -> list[str]:
    # POSIX shlex would consume Windows backslashes. Disable escapes, retaining
    # quoted paths/spaces, comments and forward/backslash path separators.
    parser = shlex.shlex(value, posix=True)
    parser.whitespace_split = True
    parser.escape = ''
    parser.commenters = '#'
    try:
        return list(parser)
    except ValueError as error:
        raise ImportError(f'Invalid material quoting: {error}') from error


def _relative(base: Path, value: str) -> Path:
    # Sidecars may reference sibling folders but are never fetched from URLs.
    if '://' in value or value.startswith(('\\\\', '//')):
        raise ImportError('Material images must be local files')
    return (base / value.replace('\\', '/')).resolve()


def read_obj_materials(obj: Path) -> tuple[dict[str, ObjMaterial], tuple[str, ...]]:
    """Read mtllib/newmtl/map_Kd/Kd/d/Tr; explain unsupported image semantics."""
    # The geometry parser has its own 4 MiB bound; use that same bound here.
    if obj.stat().st_size > 4 * 1024 * 1024:
        raise ImportError('OBJ exceeds 4 MiB')
    libraries: list[Path] = []
    warnings: list[str] = []
    for line in obj.read_text(encoding='utf-8-sig').splitlines():
        p = _tokens(line)
        if p and p[0] == 'mtllib':
            if not p[1:]:
                raise ImportError('mtllib needs a local MTL filename')
            # Support the local decomp's unquoted filename-with-spaces form.
            together = _relative(obj.parent, ' '.join(p[1:]))
            paths = [together] if together.is_file() else [_relative(obj.parent, s) for s in p[1:]]
            libraries.extend(paths)
    if len(libraries) > 16:
        raise ImportError('OBJ references more than 16 material libraries')
    result: dict[str, ObjMaterial] = {}
    def finish(material: ObjMaterial) -> None:
        if material.alpha_image is not None and material.alpha_image != material.image:
            material=replace(material,problems=material.problems+('Separate opacity maps are unsupported; combine alpha into the diffuse PNG.',))
        result[material.name]=material
    for path in dict.fromkeys(libraries):
        if path.suffix.casefold() != '.mtl' or not path.is_file():
            warnings.append(f'Material library missing or not MTL: {path.name}')
            continue
        current: ObjMaterial | None = None
        for number, line in enumerate(_text(path).splitlines(), 1):
            p = _tokens(line)
            if not p:
                continue
            kind, values = p[0], p[1:]
            if kind == 'newmtl':
                if current is not None:
                    finish(current)
                name = ' '.join(values)
                if not name or name in result:
                    raise ImportError(f'{path.name}:{number}: empty or duplicate material')
                if len(result)>=255:
                    raise ImportError('Material libraries exceed 255 definitions')
                current = ObjMaterial(name)
            elif current is not None:
                if kind in ('Kd', 'd', 'Tr'):
                    try:
                        v = tuple(float(x) for x in values)
                    except ValueError as error:
                        raise ImportError(f'{path.name}:{number}: invalid {kind}') from error
                    if len(v) != (3 if kind == 'Kd' else 1) or any(not math.isfinite(x) or not 0 <= x <= 1 for x in v):
                        raise ImportError(f'{path.name}:{number}: {kind} must be in 0..1')
                    current = replace(current, diffuse=v if kind == 'Kd' else current.diffuse,
                        opacity=(1-v[0] if kind == 'Tr' else v[0]) if kind != 'Kd' else current.opacity)
                elif kind == 'map_Kd':
                    clamp = False
                    if values[:1] == ['-clamp'] and len(values) >= 3 and values[1] in ('on', 'off'):
                        clamp = values[1] == 'on'
                        values = values[2:]
                    if not values or values[0].startswith('-'):
                        current = replace(current, problems=current.problems+('Unsupported map_Kd options; choose a PNG manually or use a ROM slot.',))
                    else:
                        image = _relative(path.parent, ' '.join(values))
                        current = replace(current, image=image, clamp=clamp)
                elif kind == 'map_d':
                    # Our OBJ exporter repeats the diffuse PNG's alpha. Other
                    # opacity maps require explicit authoring into PNG alpha.
                    alpha_values = values[2:] if values[:2] == ['-imfchan', 'a'] else []
                    if not alpha_values:
                        current = replace(current, problems=current.problems+('Separate opacity maps are unsupported; combine alpha into the diffuse PNG.',))
                    else:
                        current=replace(current,alpha_image=_relative(path.parent,' '.join(alpha_values)))
                elif kind.startswith(('map_', 'bump', 'disp', 'norm')):
                    warnings.append(f'{current.name}: {kind} is not rendered; diffuse PNG, Kd and opacity are used.')
        if current is not None:
            finish(current)
    if len(result) > 255:
        raise ImportError('Material libraries exceed 255 definitions')
    return result, tuple(dict.fromkeys(warnings))


def read_png(path: Path) -> Pixels:
    if path.suffix.casefold() != '.png' or path.stat().st_size > MAX_PNG_BYTES:
        raise ImportError('Choose a PNG no larger than 16 MiB')
    try:
        with Image.open(path) as image:
            if image.format != 'PNG' or image.width * image.height > MAX_PNG_PIXELS or getattr(image, 'n_frames', 1) != 1:
                raise ImportError('Choose a single-frame PNG up to 16 megapixels')
            return np.array(image.convert('RGBA'), np.uint8)
    except Image.DecompressionBombError as error:
        raise ImportError('PNG dimensions exceed the supported pixel budget') from error


def default_options(pixels: Pixels, material: ObjMaterial) -> TextureOptions:
    def size(n: int) -> int:
        return min(SIZES, key=lambda s: (abs(s-n), s))
    w, h = size(pixels.shape[1]), size(pixels.shape[0])
    while w*h*2 > 4096:
        if w >= h:
            w //= 2
        else:
            h //= 2
    alpha = 'Blend' if material.opacity < 1 or np.any((pixels[:,:,3] > 0) & (pixels[:,:,3] < 255)) else 'Cutout' if np.any(pixels[:,:,3] == 0) else 'Opaque'
    fmt = TextureFormat.RGBA32 if alpha == 'Blend' else TextureFormat.RGBA16
    while w*h*(4 if fmt == TextureFormat.RGBA32 else 2) > 4096:
        if w >= h:w //= 2
        else:h //= 2
    return TextureOptions(w, h, fmt, alpha, material.clamp, material.clamp)


def build_texture(pixels: Pixels, options: TextureOptions, *, diffuse: tuple[float,float,float] = (1.,1.,1.), opacity: float = 1.) -> bytes:
    if (options.width not in SIZES or options.height not in SIZES or options.format not in FORMATS
            or options.alpha not in ALPHA_MODES or type(options.clamp_u) is not bool or type(options.clamp_v) is not bool):
        raise ImportError('Choose supported power-of-two dimensions, RGBA format and alpha mode')
    if options.width*options.height*(4 if options.format == TextureFormat.RGBA32 else 2) > 4096:
        raise ImportError('Texture exceeds the N64 4 KiB TMEM budget; reduce dimensions or choose RGBA16')
    if options.alpha == 'Blend' and options.format != TextureFormat.RGBA32:
        raise ImportError('Blend needs RGBA32 to preserve partial alpha; choose Cutout for RGBA16')
    if (len(diffuse) != 3 or any(not math.isfinite(c) or not 0 <= c <= 1 for c in (*diffuse, opacity))
            or pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 4):
        raise ImportError('Invalid RGBA image or material color/opacity')
    resized = np.array(Image.fromarray(pixels).resize((options.width,options.height),Image.Resampling.NEAREST),np.uint8)
    resized[:,:,:3] = np.rint(resized[:,:,:3].astype(np.float64)*diffuse).astype(np.uint8)
    alpha = np.rint(resized[:,:,3].astype(np.float64)*opacity)
    resized[:,:,3] = 255 if options.alpha == 'Opaque' else np.where(alpha >= 128,255,0) if options.alpha == 'Cutout' else alpha.astype(np.uint8)
    # PNG top row -> ROM top row; OBJ V conversion already happens in the mesh
    # compiler, matching exporter raw PNG rows. Browser upright exchange has a
    # separate inverse flip and must not be applied a second time here.
    data = encode_pixels(resized,options.format)
    flags = (0x40 if options.clamp_u else 0) | (0x80 if options.clamp_v else 0) | (0x10 if options.alpha == 'Cutout' else 4 if options.alpha == 'Blend' else 0)
    header = bytearray(32)
    header[:3] = bytes((options.width,options.height,int(options.format)+(0 if options.alpha == 'Blend' else 16)))
    header[5] = 1
    struct.pack_into('>H',header,6,flags)
    header[18] = 1  # Engine reads numOfTextures >>8; builder writes 01 00.
    struct.pack_into('>h',header,22,32+len(data))
    return bytes(header)+data


def validate_custom_texture(raw: bytes) -> TextureHeader:
    h = TextureHeader.from_bytes(raw)
    alpha = 'Blend' if h.flags & 4 else 'Cutout' if h.flags & 0x10 else 'Opaque'
    options = TextureOptions(h.width,h.height,h.format,alpha,bool(h.flags & 0x40),bool(h.flags & 0x80))
    # Reconstruct only the canonical header; texel bytes are arbitrary. Repeated
    # quantization is intentionally avoided (RGBA16 decode/encode is lossy).
    expected = build_texture(np.full((1,1,4),255,np.uint8),options)[:32]
    if raw[:32] != expected or len(raw) != h.frame_size:
        raise ImportError('Custom texture must retain the canonical static header and exact pixel span')
    Texture.from_bytes(raw)
    return h


def texture_pool_refs(base_count: int, textures: Sequence[bytes]) -> tuple[TextureReference,...]:
    if len(textures) > MAX_CUSTOM_TEXTURES or base_count+len(textures) > 0x8000:
        raise ImportError('Dedicated texture pool exceeds the editor/15-bit asset-ID bound')
    return tuple(TextureReference(base_count+i,validate_custom_texture(raw)) for i,raw in enumerate(textures))


def material_appearance(raw: bytes, refs: Sequence[TextureReference], assignments: Mapping[str,tuple[int,int]]) -> tuple[bytes,dict[str,int]]:
    """Temporary expanded TextureInfo list, serialized canonically by compiler."""
    textures = list(LevelModel.from_bytes(raw).textures)
    mapping: dict[str,int] = {}
    for name,(index,surface) in assignments.items():
        if type(index) is not int or not 0 <= index < len(refs) or type(surface) is not int or not 0 <= surface < len(SURFACES):
            raise ImportError('Invalid custom material texture/surface')
        h = refs[index].header
        info = TextureInfo(index,h.width,h.height,h.raw[2],surface)
        if info not in textures:
            textures.append(info)
        mapping[name] = textures.index(info)
    if len(textures) > 255:
        raise ImportError('Custom materials exceed the 255 track texture-slot limit')
    out = bytearray(raw)
    out.extend(bytes(-len(out)%16))
    pointer = len(out)
    out.extend(b''.join(struct.pack('>IBBBb',t.texture_id,t.width,t.height,t.format,t.surface_type) for t in textures))
    struct.pack_into('>I',out,0,pointer)
    struct.pack_into('>h',out,0x18,len(textures))
    struct.pack_into('>i',out,0x48,len(out))
    return bytes(out),mapping


@dataclass(frozen=True)
class MaterialImage:
    material: ObjMaterial
    pixels: Pixels
    options: TextureOptions
    surface: int


def stage_artwork(appearance: bytes, refs: tuple[TextureReference,...], materials: Mapping[str,int],
                  images: Mapping[str,MaterialImage], existing: Mapping[int,bytes]) -> tuple[bytes,dict[str,int],tuple[bytes,...],tuple[TextureReference,...]]:
    """Pure staged assets/mappings. Existing ROM assets are never overwritten."""
    additions: list[bytes] = []
    lookup = {raw:index for index,raw in existing.items()}
    assignments: dict[str,tuple[int,int]] = {}
    for name,image in images.items():
        if image.material.problems:
            raise ImportError(name+': '+'; '.join(image.material.problems))
        raw = build_texture(image.pixels,image.options,diffuse=image.material.diffuse,opacity=image.material.opacity)
        index = lookup.get(raw)
        if index is None:
            index = len(refs)+len(additions)
            lookup[raw] = index
            additions.append(raw)
        assignments[name] = index,image.surface
    if len(existing)+len(additions)>MAX_CUSTOM_TEXTURES:
        raise ImportError('Dedicated texture pool exceeds 128 assets per project')
    extra = texture_pool_refs(len(refs),additions)
    combined = refs+extra
    if not assignments:
        return appearance,dict(materials),(),refs
    out,slots = material_appearance(appearance,combined,assignments)
    return out,dict(materials)|slots,tuple(additions),combined
