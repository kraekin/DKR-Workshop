"""Headless texture formats, framing, signed UVs and complete material exports."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import struct
import zlib

import numpy as np
from PIL import Image
import pytest

from src.core.exporter import export_obj
from src.core.level_model import LevelModel, load_level_model
from src.core.rom import AssetType, DecompAssets, RomImage
from src.core.textures import (
    Texture, TextureError, TextureFormat as F, TextureHeader,
    decode_pixels, deinterlace, image_size, load_model_textures, load_texture, model_uvs, normalize_uvs,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def rom() -> RomImage:
    paths = list(ROOT.glob("*.z64"))
    if not paths:
        pytest.skip("Local USA Rev 1 ROM not present")
    return RomImage.from_file(paths[0])


def frame_bytes(format: F = F.RGBA32, *, frames: int = 1, flags: int = 0,
                pixels: bytes = b"\xff\x00\x00\xff\x00\xff\x00\x00") -> bytes:
    raw = bytearray(32)
    raw[:3] = bytes((2, 1, 0x10 | format))
    raw[18] = frames
    struct.pack_into(">H", raw, 6, flags)
    struct.pack_into(">Hh", raw, 20, 16, 32 + len(pixels))
    return bytes(raw) + pixels


@pytest.mark.parametrize("format,data,expected", [
    (F.RGBA32, bytes([1, 2, 3, 4, 255, 0, 128, 0]), [[1, 2, 3, 4], [255, 0, 128, 0]]),
    (F.RGBA16, bytes.fromhex("f80107c0"), [[255, 0, 0, 255], [0, 255, 0, 0]]),
    (F.I8, bytes([0, 255]), [[0, 0, 0, 255], [255, 255, 255, 255]]),
    (F.I4, bytes([0x1F]), [[17, 17, 17, 255], [255, 255, 255, 255]]),
    (F.IA16, bytes([21, 32, 190, 0]), [[21, 21, 21, 32], [190, 190, 190, 0]]),
    (F.IA8, bytes([0xA1, 0x0F]), [[170, 170, 170, 17], [0, 0, 0, 255]]),
    (F.IA4, bytes([0xEF]), [[255, 255, 255, 0], [255, 255, 255, 255]]),
    (F.CI4, bytes([0x01]), [[255, 0, 0, 255], [0, 255, 0, 0]]),
    (F.CI8, bytes([1, 0]), [[0, 255, 0, 0], [255, 0, 0, 255]]),
])
def test_every_format_exact_pixels(format: F, data: bytes, expected: list[list[int]]) -> None:
    output = decode_pixels(data, 2, 1, format, palette=bytes.fromhex("f80107c0"))
    assert output.shape == (1, 2, 4) and output.dtype == np.uint8
    np.testing.assert_array_equal(output[0], expected)
    assert not output.flags.writeable


@pytest.mark.parametrize("format", list(F))
def test_scanline_swaps_match_local_extractor(format: F) -> None:
    width = 32
    size = image_size(width, 3, format)
    data = bytes(index % 256 for index in range(size))
    swapped = deinterlace(data, width, 3, format)
    row_size = size // 3
    half = 8 if format == F.RGBA32 else 4
    assert swapped[:row_size] == data[:row_size]
    assert swapped[row_size:row_size + half] == data[row_size + half:row_size + 2 * half]
    assert swapped[row_size + half:row_size + half * 2] == data[row_size:row_size + half]
    assert swapped[row_size * 2:] == data[row_size * 2:]
    assert deinterlace(swapped, width, 3, format) == data
    palette = bytes.fromhex("ffff") * (16 if format == F.CI4 else 256) if format in (F.CI4, F.CI8) else None
    np.testing.assert_array_equal(decode_pixels(data, width, 3, format, palette=palette),
                                  decode_pixels(swapped, width, 3, format, palette=palette, interlaced=True))


def test_odd_pixel_count_and_ci8_full_palette() -> None:
    assert decode_pixels(bytes([0xAF, 0x30]), 3, 1, F.I4)[0, :, 0].tolist() == [170, 255, 51]
    palette = bytes.fromhex("f801") * 255 + bytes.fromhex("003f")
    assert decode_pixels(bytes([255]), 1, 1, F.CI8, palette=palette)[0, 0].tolist() == [0, 0, 255, 255]


@pytest.mark.parametrize("operation", [
    lambda: decode_pixels(b"", 2, 1, F.RGBA32),
    lambda: decode_pixels(b"\0", 1, 1, 9),
    lambda: decode_pixels(b"", 0, 1, F.I8),
    lambda: decode_pixels(b"\x10", 2, 1, F.CI4),
    lambda: decode_pixels(b"\xff", 1, 1, F.CI8, palette=b"\0\0" * 64),
    lambda: decode_pixels(b"\x00", 1, 1, F.CI8, palette=b"\0"),
    lambda: Texture.from_bytes(b"\0" * 31),
    lambda: Texture.from_bytes(frame_bytes()[:-1]),
    lambda: Texture.from_bytes(frame_bytes(frames=2)),
    lambda: Texture.from_bytes(frame_bytes(F.CI4, pixels=b"\x01")),
    lambda: deinterlace(b"\0\0", 3, 1, F.I4),
])
def test_reject_invalid_texture_data(operation: object) -> None:
    with pytest.raises((ValueError, TextureError)):
        operation()


def test_compressed_outer_header_animated_stride_and_frame_selection() -> None:
    first = frame_bytes(frames=2)
    second = frame_bytes(frames=2, pixels=bytes([0, 0, 255, 255, 255, 255, 255, 255]))
    payload = first + second
    header = bytearray(first[:32])
    header[29] = 1
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = bytes(header) + struct.pack("<IB", len(payload), 9) + compressor.compress(payload) + compressor.flush()
    texture = Texture.from_bytes(packed + b"\0" * 8, texture_id=42)
    assert len(texture.frames) == 2 and texture.texture_id == 42
    assert texture.frames[1].pixels[0, 0].tolist() == [0, 0, 255, 255]
    assert [texture.frame_index(i) for i in (0, 3, 4, 7, 8, 255)] == [0, 0, 1, 1, 0, 0]
    assert texture.frames[0].header.frame_advance == 16


def test_header_wrap_non_power_of_two_and_palette_offset() -> None:
    header = TextureHeader.from_bytes(frame_bytes(flags=0xC0))
    assert header.clamp_u and header.clamp_v and header.raw[18] == 1
    raw = bytearray(frame_bytes()[:32]); raw[0] = 3
    assert TextureHeader.from_bytes(bytes(raw)).clamp_u
    raw = bytearray(frame_bytes(F.CI4, pixels=b"\x01")); struct.pack_into(">h", raw, 8, 4)
    texture = Texture.from_bytes(bytes(raw), palettes=b"\0" * 4 + bytes.fromhex("f80107c0") + b"\0" * 28)
    assert texture.frames[0].pixels[0].tolist() == [[255, 0, 0, 255], [0, 255, 0, 0]]


def test_signed_uv_scaling_orientation_and_no_clamping() -> None:
    uv = np.array([[-1024, -512], [2048, 1024], [0, 0]], dtype=np.int16)
    np.testing.assert_array_equal(normalize_uvs(uv, 32, 16), [[-1, -1], [2, 2], [0, 0]])
    np.testing.assert_array_equal(normalize_uvs(uv, 32, 16, obj=True), [[-1, 2], [2, -1], [0, 1]])
    with pytest.raises(TextureError):
        normalize_uvs(uv, 0, 16)


def test_all_1416_rev1_textures_and_1713_frames(rom: RomImage) -> None:
    formats: Counter[int] = Counter()
    frame_count = 0
    for texture_id in range(rom.count(AssetType.TEXTURES_3D)):
        texture = load_texture(rom, texture_id)
        frame_count += len(texture.frames)
        for frame in texture.frames:
            assert frame.pixels.shape == (frame.header.height, frame.header.width, 4)
            assert frame.to_image().mode == "RGBA"
        formats[int(texture.frames[0].header.format)] += 1
    assert frame_count == 1713
    assert formats == {0: 237, 1: 1136, 2: 2, 3: 3, 5: 37, 6: 1}
    assert rom.section(AssetType.EMPTY_14) == b""


@pytest.mark.parametrize("model_id", range(55))
def test_every_models_texture_references_and_uvs(rom: RomImage, model_id: int) -> None:
    model = load_level_model(rom, model_id)
    textures = load_model_textures(rom, model)
    uv = model_uvs(model, textures)
    assert uv.shape == (model.triangle_count, 3, 2) and np.isfinite(uv).all()
    for segment in model.segments:
        for batch, following in zip(segment.batches, (*segment.batches[1:], segment.terminal_batch)):
            if batch.texture_index == 255:
                continue
            texture = textures[model.textures[batch.texture_index].texture_id]
            header = texture.frames[texture.frame_index(batch.texture_offset)].header
            expected = segment.uvs[batch.faces_offset:following.faces_offset] / [header.width * 32, header.height * 32]
            np.testing.assert_allclose(uv[segment.face_base + batch.faces_offset:segment.face_base + following.faces_offset], expected)


def test_obj_mtl_png_seams_materials_and_original_winding(rom: RomImage, tmp_path: Path) -> None:
    model = load_level_model(rom, 5)
    textures = load_model_textures(rom, model)
    result = export_obj(model, tmp_path / "Ancient Lake.obj", textures=textures)
    lines = result.path.read_text().splitlines()
    vt = np.array([[float(v) for v in line.split()[1:]] for line in lines if line.startswith("vt ")])
    faces = [line.split()[1:] for line in lines if line.startswith("f ")]
    positions = np.array([[int(field.split('/')[0]) for field in face] for face in faces])
    texrefs = np.array([[int(field.split('/')[1]) for field in face] for face in faces])
    np.testing.assert_array_equal(positions - 1, model.indices)
    np.testing.assert_array_equal(texrefs.reshape(-1), np.arange(1, model.triangle_count * 3 + 1))
    np.testing.assert_allclose(vt, model_uvs(model, textures, obj=True).reshape(-1, 2), atol=1e-7)
    assert result.material_path is not None and ' ' not in result.material_path.name
    assert f'mtllib {result.material_path.name}' in lines
    mtl = result.material_path.read_text()
    used = {line.split()[1] for line in lines if line.startswith('usemtl ')}
    defined = {line.split()[1] for line in mtl.splitlines() if line.startswith('newmtl ')}
    assert used <= defined
    assert result.texture_paths
    for png in result.texture_paths:
        texture_id, frame_index = (int(png.stem.split('_')[i]) for i in (1, 3))
        with Image.open(png) as image:
            np.testing.assert_array_equal(np.array(image), textures[texture_id].frames[frame_index].pixels)
    for line in mtl.splitlines():
        if line.startswith('map_Kd '):
            assert (result.path.parent / line.removeprefix('map_Kd ')).is_file()
    # Repeat exports are stable and do not duplicate texture folders.
    export_obj(model, result.path, textures=textures)
    assert len(list(tmp_path.glob('*_textures_*'))) == 1


def test_textured_export_failure_preserves_prior_obj_and_mtl(rom: RomImage, tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    model = load_level_model(rom, 5)
    textures = load_model_textures(rom, model)
    obj = tmp_path / 'track.obj'; obj.write_text('old obj')
    mtl = obj.with_suffix('.mtl'); mtl.write_text('old mtl')
    replace = Path.replace

    def fail_obj(self: Path, target: Path) -> Path:
        if Path(target) == obj:
            raise PermissionError('locked OBJ')
        return replace(self, target)

    monkeypatch.setattr(Path, 'replace', fail_obj)
    with pytest.raises(PermissionError):
        export_obj(model, obj, textures=textures)
    assert obj.read_text() == 'old obj' and mtl.read_text() == 'old mtl'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['track.mtl', 'track.obj']


def test_extracted_texture_json_png_flip_and_path_safety(tmp_path: Path) -> None:
    Image.fromarray(np.array([[[255, 0, 0, 255]], [[0, 0, 255, 255]]], dtype=np.uint8)).save(tmp_path / 'image.png')
    metadata = {'format': 'RGBA16', 'images': ['image.png'], 'flipped-image': True,
                'flags': {'wrap-s': 'Clamp', 'wrap-t': 'Wrap'}, 'render-mode': 'OPAQUE'}
    for name, content in {
        'assets.meta.json': {'@dkr-version': 'us.v80', 'assets': {'sections': {'ASSET_TEXTURES_3D': {'filename': 'textures.meta.json'}}}},
        'textures.meta.json': {'files': {'order': ['TEXTURE_TEST'], 'sections': {'TEXTURE_TEST': {'filename': 'texture.json'}}}},
        'texture.json': metadata,
    }.items():
        (tmp_path / name).write_text(json.dumps(content))
    source = DecompAssets.from_directory(tmp_path)
    texture = load_texture(source, 0)
    assert texture.frames[0].pixels[0, 0].tolist() == [0, 0, 255, 255]
    assert texture.frames[0].header.clamp_u
    metadata['images'] = ['../outside.png']
    (tmp_path / 'texture.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='outside'):
        load_texture(source, 0)
