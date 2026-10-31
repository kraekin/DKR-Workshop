"""Batch IDs/orientation, multi-frame merge, atomic refusals and UI review."""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from PIL import Image
import pytest

from src.core.editing import EditSession
from src.core.image_batch import (export_image_batch, stage_image_batch, apply_image_batch, changed_image)
from src.core.rom import AssetType, RomImage
from src.core.textures import TextureHeader


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


@pytest.mark.parametrize("sheets", [False, True])
def test_no_edit_round_trip_is_byte_identical(rom: RomImage, tmp_path: Path, sheets: bool) -> None:
    s = EditSession(rom)
    keys = ((AssetType.TEXTURES_3D, 0), (AssetType.TEXTURES_2D, 18), (AssetType.SPRITES, 1))
    manifest = export_image_batch(s, keys, tmp_path / "batch", sheets=sheets)
    plan = stage_image_batch(s, manifest)
    assert not plan.changes and not apply_image_batch(s, plan) and not s.dirty
    assert s.build_rom() is rom.data


@pytest.mark.parametrize("sheets", [False, True])
def test_two_frames_merge_and_one_undo(rom: RomImage, tmp_path: Path, sheets: bool) -> None:
    s = EditSession(rom)
    section = AssetType.TEXTURES_3D
    index = next(i for i in range(rom.count(section)) if TextureHeader.from_bytes(rom.read_asset(section, i)).frame_count > 1)
    original = s.current_asset(section, index)
    manifest = export_image_batch(s, ((section, index),), tmp_path / "batch", sheets=sheets)
    entries = json.loads(manifest.read_text())["entries"]
    for entry, color in zip(entries[:2], ((255, 0, 0, 255), (0, 255, 0, 255))):
        path = manifest.parent / entry["file"]
        with Image.open(path) as image:
            pixels = np.array(image.convert("RGBA"))
        pixels[entry["y"]:entry["y"] + entry["height"], entry["x"]:entry["x"] + entry["width"]] = color
        Image.fromarray(pixels).save(path)
    plan = stage_image_batch(s, manifest)
    assert not s.dirty and len(plan.changes) == 1
    assert apply_image_batch(s, plan)
    frames = s.image_texture(section, index).frames
    assert not np.array_equal(frames[0].pixels, frames[1].pixels)
    assert changed_image(s, (section, index))
    s.undo()
    assert s.current_asset(section, index) == original and not s.dirty
    s.redo()
    with pytest.raises(ValueError, match="changed after preview"):
        apply_image_batch(s, plan)


def test_bad_manifest_paths_dimensions_and_partial_failure_are_atomic(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    manifest = export_image_batch(s, ((AssetType.TEXTURES_2D, 18),), tmp_path / "batch")
    original = json.loads(manifest.read_text())
    for mutation in (dict(file="../../outside.png"), dict(width=1), dict(frame=999), dict(index=-1), dict(flip_y=1)):
        document = json.loads(json.dumps(original))
        document["entries"][0].update(mutation)
        manifest.write_text(json.dumps(document))
        with pytest.raises(ValueError):
            stage_image_batch(s, manifest)
        assert not s.dirty and not s.can_undo
    manifest.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="existing files"):
        export_image_batch(s, ((AssetType.TEXTURES_2D, 18),), manifest.parent)


def test_edited_sprite_package_preview_and_apply(rom: RomImage, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication
    from src.ui.image_batch import BatchImageDialog
    app = QApplication.instance() or QApplication([])
    s = EditSession(rom)
    key = AssetType.SPRITES, 1
    manifest = export_image_batch(s, (key,), tmp_path / "batch")
    entry = json.loads(manifest.read_text())["entries"][0]
    image_path = manifest.parent / entry["file"]
    with Image.open(image_path) as image:
        pixels = np.array(image.convert("RGBA"))
    pixels[0:5, 0:5] = (255, 255, 255, 255)
    Image.fromarray(pixels).save(image_path)
    dialog = BatchImageDialog(s, (key,), (key,))
    dialog.review(manifest)
    assert dialog.plan is not None and dialog.apply.isEnabled(), dialog.report.toPlainText()
    assert not s.dirty
    dialog.apply_plan()
    assert changed_image(s, key)
    s.undo()
    assert not s.dirty
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def test_added_custom_texture_is_in_changed_images(rom: RomImage) -> None:
    from src.core.track_artwork import build_texture, TextureOptions
    s = EditSession(rom)
    pixels = np.full((8, 8, 4), 255, np.uint8)
    s._set_texture_pool((build_texture(pixels, TextureOptions(8, 8)),))
    index = rom.count(AssetType.TEXTURES_3D)
    assert changed_image(s, (AssetType.TEXTURES_3D, index))
