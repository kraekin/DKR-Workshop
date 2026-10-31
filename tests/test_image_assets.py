"""encoders, PNG interchange, image overlays and bounded ROM rebuilding."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import struct
import numpy as np
import pytest
from PIL import Image, PngImagePlugin

from src.core.editing import EditSession, EditError, n64_checksums
from src.core.rom import AssetType, RomImage, DecompAssets, LUT_START, LUT_END, REV1_SHA1, parse_asset_lut
from src.core.textures import TextureFormat, TextureHeader, TextureError, image_size, decode_pixels, load_texture
from src.core.materials import MaterialEdit
from src.core.image_assets import (encode_pixels, unpack_texture, pack_texture, frame_spans,
    texture_from_raw, replace_frame, validate_texture_edit, edit_timing, edit_anchor,
    validate_sprite_edit, sprite_canvas, split_sprite_png, read_png, export_png, TEXTURE_SECTIONS, SpriteCanvas,
    png_flip_default, png_rows)
from src.core.editing import compress_asset


@pytest.fixture(scope="module")
def session() -> EditSession:
    return EditSession(RomImage.from_file(next(Path.cwd().glob("*.z64"))))


def fixture_texture(fmt: TextureFormat, *, compressed: bool = True, frames: int = 2,
                    width: int = 18, height: int = 3, interlace: bool = False) -> bytes:
    raw = bytearray()
    for index in range(frames):
        size = image_size(width, height, fmt)
        header = bytearray(32)
        header[:3] = bytes((width, height, int(fmt)))
        header[18] = frames
        struct.pack_into(">H", header, 6, 0x400 if interlace else 0)
        struct.pack_into(">Hh", header, 20, 256, (32 + size + 15) // 16 * 16)
        raw.extend(header)
        raw.extend(np.random.default_rng(index + 321).integers(0, 256, size, dtype=np.uint8).tobytes())
        raw.extend(bytes([0xAC]) * (-len(raw) % 16))
    outer = bytearray(raw[:32]); outer[29] = 1
    return bytes(outer) + compress_asset(bytes(raw)) if compressed else bytes(raw)


@pytest.mark.parametrize("fmt", list(TextureFormat)[:7])
@pytest.mark.parametrize("interlaced", [False, True])
def test_codecs_match_local_quantization_and_row_swaps(fmt: TextureFormat, interlaced: bool) -> None:
    p = np.random.default_rng(16).integers(0, 256, (3, 18, 4), dtype=np.uint8)
    p[0, 0] = [255, 0, 128, 0]
    p[0, 1] = [1, 17, 36, 1]
    raw = encode_pixels(p, fmt, interlaced=interlaced)
    decoded = decode_pixels(raw, 18, 3, fmt, interlaced=interlaced)
    assert len(raw) == image_size(18, 3, fmt)
    if fmt == TextureFormat.RGBA32:
        np.testing.assert_array_equal(decoded, p)
    elif fmt == TextureFormat.RGBA16:
        rgb = ((p[:, :, :3].astype(np.uint32) + 4) * 31 // 255) * 255 // 31
        np.testing.assert_array_equal(decoded[:, :, :3], rgb)
        np.testing.assert_array_equal(decoded[:, :, 3], (p[:, :, 3] != 0) * 255)
    else:
        intensity = (p[:, :, :3].astype(np.uint32).sum(axis=2) + 1) // 3
        if fmt in (TextureFormat.I4, TextureFormat.IA8): intensity = intensity // 17 * 17
        if fmt == TextureFormat.IA4: intensity = intensity // 36 * 255 // 7
        np.testing.assert_array_equal(decoded[:, :, 0], intensity)
        np.testing.assert_array_equal(decoded[:, :, 1], intensity)
        alpha = ((p[:, :, 3] != 0) * 255 if fmt == TextureFormat.IA4 else p[:, :, 3] // 17 * 17 if fmt == TextureFormat.IA8 else p[:, :, 3] if fmt == TextureFormat.IA16 else np.full(p.shape[:2], 255))
        np.testing.assert_array_equal(decoded[:, :, 3], alpha)
    assert encode_pixels(decoded, fmt, interlaced=interlaced) == raw


@pytest.mark.parametrize("fmt", [TextureFormat.CI4, TextureFormat.CI8])
def test_ci_uses_existing_palette_only(fmt: TextureFormat) -> None:
    palette = struct.pack(">4H", 0xF801, 0x07C1, 0x003F, 0)
    pixels = np.array([[[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255], [0, 0, 0, 0]]], np.uint8)
    raw = encode_pixels(pixels, fmt, palette=palette)
    np.testing.assert_array_equal(decode_pixels(raw, 4, 1, fmt, palette=palette), pixels)
    assert raw == (b"\x01\x23" if fmt == TextureFormat.CI4 else b"\0\1\2\3")
    with pytest.raises(ValueError): encode_pixels(pixels, fmt)


@pytest.mark.parametrize("fmt", list(TextureFormat)[:7])
@pytest.mark.parametrize("compressed", [False, True])
def test_frame_patch_keeps_headers_other_frames_padding_and_wrapping(fmt: TextureFormat, compressed: bool) -> None:
    stored = fixture_texture(fmt, compressed=compressed, interlace=True)
    raw = unpack_texture(stored)
    texture = texture_from_raw(raw)
    assert replace_frame(raw, 0, texture.frames[0].pixels) == raw
    pixels = texture.frames[0].pixels.copy(); pixels[1, 0] = 255 - pixels[1, 0]
    updated = replace_frame(raw, 0, pixels)
    validate_texture_edit(raw, updated)
    span = frame_spans(raw)[0]
    changed = {i for i, (a, b) in enumerate(zip(raw, updated)) if a != b}
    assert changed and changed <= set(range(span.start, span.end))
    np.testing.assert_array_equal(texture_from_raw(updated).frames[1].pixels, texture.frames[1].pixels)
    restored = replace_frame(updated, 0, texture.frames[0].pixels)
    assert restored == raw
    assert TextureHeader.from_bytes(pack_texture(updated)).compressed == compressed
    np.testing.assert_array_equal(texture_from_raw(unpack_texture(pack_texture(updated))).frames[0].pixels,
                                  texture_from_raw(updated).frames[0].pixels)


def test_odd_nibble_noop_alpha_and_protected_bytes() -> None:
    raw = unpack_texture(fixture_texture(TextureFormat.IA4, compressed=False, frames=1, width=3, height=1))
    spans = frame_spans(raw); span = spans[0]
    pixel = texture_from_raw(raw).frames[0].pixels.copy(); pixel[0, 0] = [255, 255, 255, 0]
    updated = replace_frame(raw, 0, pixel)
    assert updated[span.end - 1] == raw[span.end - 1]
    validate_texture_edit(raw, updated)
    for offset in (0, 2, 3, 5, 6, 8, 18, 22, 29, len(raw) - 1):
        bad = bytearray(raw); bad[offset] ^= 1
        with pytest.raises(ValueError): validate_texture_edit(raw, bytes(bad))
    with pytest.raises(ValueError): validate_texture_edit(raw, raw + b"\0")
    with pytest.raises(ValueError): replace_frame(raw, 1, pixel)
    with pytest.raises(ValueError): replace_frame(raw, 0, pixel[:0])
    with pytest.raises(ValueError): encode_pixels(pixel.astype(np.float32), TextureFormat.RGBA32)


def test_timing_and_anchor_have_separate_exact_masks() -> None:
    raw = unpack_texture(fixture_texture(TextureFormat.RGBA32))
    updated = edit_timing(raw, 600)
    allowed = {20, 21} | {span.offset + d for span in frame_spans(raw) for d in (20, 21)}
    assert {i for i, (a, b) in enumerate(zip(raw, updated)) if a != b} <= allowed
    validate_texture_edit(raw, updated)
    assert all(span.header.frame_advance == 600 for span in frame_spans(updated))
    sprite = struct.pack(">4hi", 0, 1, 5, -7, 0x12345678) + b"\0\1\xAA\xBB"
    changed = edit_anchor(sprite, -32768, 32767)
    validate_sprite_edit(sprite, changed)
    assert changed[:4] == sprite[:4] and changed[8:] == sprite[8:]
    for offset in (0, 2, 8, 12, 15):
        bad = bytearray(sprite); bad[offset] ^= 1
        with pytest.raises(ValueError): validate_sprite_edit(sprite, bytes(bad))
    for value in (-1, 65536, True):
        with pytest.raises(ValueError): edit_timing(raw, value)
    with pytest.raises(ValueError): edit_anchor(sprite, 32768, 0)


def test_all_stock_texture_frames_noedit_identity_and_png_roundtrip(session: EditSession, tmp_path: Path) -> None:
    counts = []
    for section in sorted(TEXTURE_SECTIONS):
        for index in range(session.rom.count(section)):
            raw = session.original_asset(section, index)
            tex = session.image_texture(section, index)
            assert edit_timing(raw, tex.frames[0].header.frame_advance) == raw
            for frame, data in enumerate(tex.frames):
                assert replace_frame(raw, frame, data.pixels) == raw
                flip = png_flip_default(session.asset_source, section, index)
                exported = png_rows(data.pixels, flip_y=flip)
                imported = png_rows(exported, flip_y=flip)
                assert replace_frame(raw, frame, imported) == raw
            counts.append((section, index))
    assert len(counts) == 2332 and not session.dirty and session.build_rom() is session.rom.data
    canvas = sprite_canvas(session.asset_source, 1)
    png = export_png(canvas.pixels, tmp_path / "minimap.png")
    np.testing.assert_array_equal(read_png(png, (canvas.pixels.shape[1], canvas.pixels.shape[0])), canvas.pixels)
    assert not session.import_image(AssetType.SPRITES, 1, 0, read_png(png, (32, 68)))


def test_png_rejects_size_type_animation_and_keeps_existing_destination(tmp_path: Path) -> None:
    pixels = np.zeros((4, 5, 4), np.uint8)
    path = export_png(pixels, tmp_path / "art.png")
    assert read_png(path, (5, 4)).shape == pixels.shape
    with pytest.raises(ValueError): read_png(path, (5, 5))
    jpeg = tmp_path / "fake.png"; Image.new("RGB", (5, 4)).save(jpeg, format="JPEG")
    with pytest.raises(ValueError): read_png(jpeg, (5, 4))
    animated = tmp_path / "animated.png"
    Image.new("RGBA", (5, 4)).save(animated, save_all=True, append_images=[Image.new("RGBA", (5, 4), "red")])
    with pytest.raises(ValueError): read_png(animated, (5, 4))
    wrong = tmp_path / "keep.txt"; wrong.write_text("keep")
    with pytest.raises(ValueError): export_png(pixels, wrong)
    assert wrong.read_text() == "keep"


@pytest.mark.parametrize("fmt", list(TextureFormat)[:7])
def test_upright_png_inverse_import_preserves_rows_swaps_and_other_frames(fmt: TextureFormat, tmp_path: Path) -> None:
    raw = unpack_texture(fixture_texture(fmt, interlace=True))
    original = texture_from_raw(raw).frames[0].pixels
    path = export_png(original, tmp_path / "upright.png", asset_type=AssetType.TEXTURES_3D, flip_y=True)
    np.testing.assert_array_equal(read_png(path, (18, 3)), original[::-1])
    imported = read_png(path, (18, 3), asset_type=AssetType.TEXTURES_3D, flip_y=True)
    assert replace_frame(raw, 0, imported) == raw
    # Simulate an image editor that drops all DKR PNG metadata.
    edited = read_png(path, (18, 3)).copy()
    edited[0, 0] = 255 - edited[0, 0]
    Image.fromarray(edited).save(path)
    imported = read_png(path, (18, 3), asset_type=AssetType.TEXTURES_3D, flip_y=True)
    np.testing.assert_array_equal(imported, edited[::-1])
    result = replace_frame(raw, 0, imported)
    validate_texture_edit(raw, result)
    decoded = texture_from_raw(result)
    assert np.any(decoded.frames[0].pixels[-1, 0] != original[-1, 0])
    np.testing.assert_array_equal(decoded.frames[0].pixels[:-1], original[:-1])
    np.testing.assert_array_equal(decoded.frames[1].pixels, texture_from_raw(raw).frames[1].pixels)


@pytest.mark.parametrize("flip", [True, False])
def test_png_orientation_tag_overrides_mode_without_double_flip(flip: bool, tmp_path: Path) -> None:
    pixels = np.random.default_rng(1901).integers(0, 256, (3, 5, 4), np.uint8)
    path = export_png(pixels, tmp_path / "tagged.png", asset_type=AssetType.TEXTURES_3D, flip_y=flip)
    for mode in (True, False):
        np.testing.assert_array_equal(read_png(path, (5, 3), asset_type=AssetType.TEXTURES_3D, flip_y=mode), pixels)
    with Image.open(path) as image:
        assert image.info["dkr-png-rows"] == ("flip-y" if flip else "stored")
    # Copying art into 2D uses the visible PNG, not the 3D source's convention.
    np.testing.assert_array_equal(read_png(path, (5, 3), asset_type=AssetType.TEXTURES_2D), pixels[::-1] if flip else pixels)


def test_legacy_untagged_png_mode_and_invalid_orientation(tmp_path: Path) -> None:
    pixels = np.random.default_rng(91).integers(0, 256, (3, 5, 4), np.uint8)
    path = export_png(pixels, tmp_path / "legacy-raw.png")
    np.testing.assert_array_equal(read_png(path, (5, 3), asset_type=AssetType.TEXTURES_3D, flip_y=False), pixels)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("dkr-asset-section", "2")
    metadata.add_text("dkr-png-rows", "invalid")
    Image.fromarray(pixels).save(path, pnginfo=metadata)
    with pytest.raises(ValueError, match="orientation"):
        read_png(path, (5, 3), asset_type=AssetType.TEXTURES_3D, flip_y=True)


def test_extractor_orientation_defaults_and_json_override(session: EditSession, tmp_path: Path) -> None:
    assert png_flip_default(session.rom, AssetType.TEXTURES_3D, 186)
    assert not png_flip_default(session.rom, AssetType.TEXTURES_2D, 0)
    assert not png_flip_default(session.rom, AssetType.SPRITES, 1)
    metadata_path = tmp_path / "texture.json"
    source = DecompAssets(tmp_path, {"assets": {"sections": {"ASSET_TEXTURES_3D": {"filename": "section.json"}}}})
    (tmp_path / "section.json").write_text(json.dumps({"files": {"order": ["TEX"], "sections": {"TEX": {"filename": "texture.json"}}}}))
    for metadata, expected in (({"images": ["image.png"], "flipped-image": True}, True),
                               ({"images": ["image.png"]}, False),
                               ({"images": ["image.png"], "flipped-image": False}, False),
                               ({"raw": "texture.bin"}, True)):
        metadata_path.write_text(json.dumps(metadata))
        assert png_flip_default(source, AssetType.TEXTURES_3D, 0) is expected
    metadata_path.write_text(json.dumps({"images": ["image.png"], "flipped-image": "yes"}))
    with pytest.raises(ValueError, match="boolean"):
        png_flip_default(source, AssetType.TEXTURES_3D, 0)


def test_sprite_layouts_all193_and_atomic_multi_tile_import(session: EditSession) -> None:
    assembled = sheets = empty = 0
    multi: tuple[int, int] | None = None
    for index in range(session.rom.count(AssetType.SPRITES)):
        from src.core.textures import load_sprite
        sprite = load_sprite(session.asset_source, index)
        for frame in range(sprite.frame_count):
            if not sprite.texture_ids(frame):
                empty += 1
                with pytest.raises(ValueError): sprite_canvas(session.asset_source, index, frame)
                continue
            canvas = sprite_canvas(session.asset_source, index, frame)
            tiles = split_sprite_png(canvas, canvas.pixels)
            assert len(tiles) == len(sprite.texture_ids(frame))
            if canvas.layout.startswith("Tile sheet"): sheets += 1
            else: assembled += 1
            if len(tiles) >= 2 and multi is None: multi = index, frame
    assert assembled > 0 and sheets > 0 and empty > 0 and multi
    s = EditSession(session.rom)
    index, frame = multi
    canvas = sprite_canvas(s.asset_source, index, frame)
    pixels = canvas.pixels.copy()
    for _, x, y, width, height in canvas.tiles: pixels[y:y + height, x:x + width] = [0, 255, 0, 255]
    assert s.import_image(AssetType.SPRITES, index, frame, pixels)
    assert len(s._assets) >= 2 and s._cursor == 1
    after = dict(s._assets)
    s.undo(); assert not s.dirty and not s._assets
    s.redo(); assert s._assets == after
    s.revert_image(AssetType.SPRITES, index); assert not s.dirty
    bad = pixels[:-1]
    with pytest.raises(ValueError): s.import_image(AssetType.SPRITES, index, frame, bad)
    assert not s.dirty


def test_sprite_empty_space_rejected_and_anchor_does_not_shift_png(session: EditSession) -> None:
    s = EditSession(session.rom)
    canvas = sprite_canvas(s.asset_source, 1)
    s.set_sprite_anchor(1, 123, -234)
    np.testing.assert_array_equal(sprite_canvas(s.asset_source, 1).pixels, canvas.pixels)
    synthetic = SpriteCanvas(
        np.zeros((2, 3, 4), np.uint8), ((0, 0, 0, 2, 2),), "test")
    changed = synthetic.pixels.copy(); changed[0, 2] = 255
    with pytest.raises(ValueError, match="empty space"): split_sprite_png(synthetic, changed)


def test_mixed_image_project_rom_roundtrip_and_untouched_entries(session: EditSession, tmp_path: Path) -> None:
    s = EditSession(session.rom)
    tile_id = sprite_canvas(s.asset_source, 1).tiles[0][0]
    for section, index in ((AssetType.TEXTURES_3D, 0), (AssetType.TEXTURES_2D, tile_id)):
        p = s.image_texture(section, index).frames[0].pixels.copy(); p[:] = [0, 255, 0, 255]
        s.import_image(section, index, 0, p)
    s.set_sprite_anchor(1, 40, 65)
    s.edit_minimap(5, {"red": 180})
    s.edit_track_materials(5, (MaterialEdit("surface", (0,), 2),))
    s.set_level_field(5, "laps", 2)
    project = s.save_project(tmp_path / "images.dkrproj", 5)
    assert json.loads(project.read_text())["version"] == 6
    loaded = EditSession.load_project(project)
    assert loaded._assets == s._assets and not loaded.dirty
    report = loaded.export_report()
    assert {diff.section for diff in report.assets} == {2, 4, 12, 23, 27}
    assert any("Sprite" in row for diff in report.assets if diff.section == 4 for row in diff.changes)
    output = loaded.build_rom()  # No ROM file is generated for gameplay.
    rebuilt = RomImage(output, "z64", parse_asset_lut(output, LUT_START, LUT_END))
    for (section, index), raw in loaded._assets.items():
        if section in TEXTURE_SECTIONS: assert unpack_texture(rebuilt.read_asset(section, index)) == raw
        elif section == AssetType.LEVEL_MODELS: assert rebuilt.read_asset(section, index, decompress=True) == raw
        else: assert rebuilt.read_asset(section, index) == raw
    for section in (AssetType.TEXTURES_3D, AssetType.TEXTURES_2D, AssetType.SPRITES):
        assert rebuilt.count(section) == s.rom.count(section)
        for index in range(s.rom.count(section)):
            if (section, index) not in loaded._assets: assert rebuilt.read_asset(section, index) == s.rom.read_asset(section, index)
    for section in range(50):
        if section not in (2, 3, 4, 5, 12, 13, 23, 26, 27): assert rebuilt.section(section) == s.rom.section(section)
    assert len(output) == len(s.rom.data) and struct.unpack_from(">2I", output, 16) == n64_checksums(output)
    assert hashlib.sha1(s.rom.source_path.read_bytes()).hexdigest() == REV1_SHA1


def test_capacity_failure_keeps_output_and_known_shared_uses(session: EditSession, tmp_path: Path) -> None:
    s = EditSession(session.rom)
    pixels = s.image_texture(AssetType.TEXTURES_3D, 0).frames[0].pixels.copy()
    pixels[:] = np.random.default_rng(1640).integers(0, 256, pixels.shape, dtype=np.uint8)
    s.import_image(AssetType.TEXTURES_3D, 0, 0, pixels)
    report = s.export_report()
    assert report.growth_bytes > 0
    key = (AssetType.TEXTURES_2D, sprite_canvas(s.asset_source, 1).tiles[0][0])
    assert any("Sprite 1" in row for row in s.image_uses.direct[key])
    assert any("Ancient Lake" in row for row in s.image_uses.levels[key])
    protected = bytearray(s.rom.data); protected[s.rom.sections[-1].end] = 1
    s.rom = RomImage(bytes(protected), "z64", s.rom.sections, s.rom.source_path); s._report_cache = None
    assert not s.export_report().can_export
    target = tmp_path / "existing.z64"; target.write_bytes(b"keep existing output")
    with pytest.raises(EditError, match="padding"): s.save_rom(target)
    assert target.read_bytes() == b"keep existing output"


def test_known_use_cache_tracks_references_without_rescanning_positions_or_pixels(session: EditSession) -> None:
    s = EditSession(session.rom)
    uses = s.image_uses
    obj = s.object((5, 48))
    s.set_position(obj.key, (obj.position[0] + 1, *obj.position[1:]))
    assert s.image_uses is uses
    s.set_sprite_anchor(1, 10, 20)
    assert s.image_uses is uses
    p = s.image_texture(AssetType.TEXTURES_3D, 0).frames[0].pixels.copy(); p[0, 0] = 255 - p[0, 0]
    s.import_image(AssetType.TEXTURES_3D, 0, 0, p)
    assert s.image_uses is uses
    s.edit_minimap(5, {"sprite": 3})
    assert s._image_uses is None
    assert "5: Ancient Lake" in s.image_uses.levels[AssetType.SPRITES, 3]
    assert not any("Ancient Lake" in name for name in s.image_uses.levels.get((AssetType.SPRITES, 1), set()))


@pytest.mark.parametrize("variant", ["old_version", "encoding", "hash", "dimensions", "format", "count", "reserved", "sprite_link"])
def test_image_projects_cannot_bypass_field_gates(session: EditSession, tmp_path: Path, variant: str) -> None:
    s = EditSession(session.rom)
    s.set_texture_timing(AssetType.TEXTURES_3D, 0, 400)
    doc = s.project_document()
    edit = doc["asset_edits"][0]
    raw = s.original_asset(AssetType.TEXTURES_3D, 0)
    if variant == "old_version": doc["version"] = 5
    if variant == "encoding": edit["encoding"] = "raw"
    if variant == "hash": edit["base_asset_sha1"] = "bad"
    offsets = {"dimensions": 32, "format": 34, "count": 50, "reserved": 31}
    if variant in offsets:
        offset = offsets[variant]; edit["bytes"].append({"offset": offset, "value": raw[offset] ^ 1})
    if variant == "sprite_link":
        s = EditSession(session.rom); s.set_sprite_anchor(1, 20, 30); doc = s.project_document()
        raw = s.original_asset(AssetType.SPRITES, 1)
        doc["asset_edits"][0]["bytes"].append({"offset": 12, "value": raw[12] ^ 1})
    path = tmp_path / "bad.dkrproj"; path.write_text(json.dumps(doc))
    with pytest.raises(ValueError): EditSession.load_project(path)
