"""Generated pixels, exact HUD transforms, atomic history and stale previews."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.image_assets import sprite_canvas
from src.core.minimap import MinimapSettings, project_markers, load_minimap_tiles
from src.core.minimap_generation import (MinimapGenerationOptions, generate_minimap,
    apply_generated_minimap, minimap_faces, rasterize_minimap)
from src.core.rom import RomImage, AssetType, LUT_START, LUT_END, parse_asset_lut


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_projection_matches_raster_for_both_adventures(rom: RomImage, angle: int) -> None:
    session = EditSession(rom)
    options = MinimapGenerationOptions(rotation=angle)
    plan = generate_minimap(session, 5, options)
    sprite, tiles = load_minimap_tiles(session.asset_source, plan.sprite_id)
    origin = (tiles[0].left + sprite.anchor[0], sprite.anchor[1] - tiles[0].top - 1)
    triangles = minimap_faces(session.track_model(5), options)
    centers = triangles.mean(axis=1)[:, (0, 2)]
    normal = project_markers(plan.settings, centers, sprite.anchor)
    mirrored = project_markers(plan.settings, centers, sprite.anchor, mirrored=True)
    np.testing.assert_allclose(mirrored[:, 0], -sprite.anchor[0] - normal[:, 0], atol=1e-10)
    np.testing.assert_allclose(mirrored[:, 1], normal[:, 1], atol=1e-10)
    x = np.rint(normal[:, 0] + sprite.anchor[0] - origin[0]).astype(int)
    y = np.rint(sprite.anchor[1] - origin[1] - 1 - normal[:, 1]).astype(int)
    assert x.min() >= 0 and y.min() >= 0
    assert x.max() < plan.pixels.shape[1] and y.max() < plan.pixels.shape[0]
    assert np.mean(plan.pixels[y, x, 3] > 0) > .95


def test_atomic_history_project_and_in_memory_export(rom: RomImage, tmp_path: Path) -> None:
    session = EditSession(rom)
    plan = generate_minimap(session, 5, MinimapGenerationOptions())
    assert not session.dirty
    assert apply_generated_minimap(session, plan)
    session.save_project(tmp_path / "minimap.dkrproj")
    loaded = EditSession.load_project(tmp_path / "minimap.dkrproj")
    for key, before, after in plan.changes:
        assert loaded.current_asset(*key) == after
    data = session.build_rom()
    exported = RomImage(data, "z64", parse_asset_lut(data, LUT_START, LUT_END))
    assert exported.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True) == plan.changes[-1][2]
    session.undo()
    assert session.dirty  # The saved project contains the generated map.
    for key, before, after in plan.changes:
        assert session.current_asset(*key) == before
    session.redo()
    assert not session.dirty


def test_stale_preview_is_rejected_without_partial_image_changes(rom: RomImage) -> None:
    session = EditSession(rom)
    plan = generate_minimap(session, 5, MinimapGenerationOptions())
    session.edit_minimap(5, {"red": 5})
    with pytest.raises(ValueError, match="changed after preview"):
        apply_generated_minimap(session, plan)
    for key, before, after in plan.changes:
        if key[0] != AssetType.LEVEL_MODELS:
            assert session.current_asset(*key) == before


def test_empty_surface_and_invalid_padding_do_not_edit(rom: RomImage) -> None:
    session = EditSession(rom)
    for options in (MinimapGenerationOptions(surfaces=()), MinimapGenerationOptions(padding=100),
                    MinimapGenerationOptions(rotation=45), MinimapGenerationOptions(minimum_up=float("nan"))):
        with pytest.raises(ValueError):
            generate_minimap(session, 5, options)
    assert not session.dirty


def test_generator_dialog_preview_apply_and_cancel(rom: RomImage) -> None:
    from PySide6.QtWidgets import QApplication
    from src.ui.minimap_generator import MinimapGeneratorDialog
    app = QApplication.instance() or QApplication([])
    session = EditSession(rom)
    dialog = MinimapGeneratorDialog(session, 5)
    dialog.generate_preview()
    assert dialog.plan is not None, dialog.details.toPlainText()
    assert dialog.apply.isEnabled() and not session.dirty
    dialog.padding.setValue(4)
    assert dialog.plan is None and not dialog.apply.isEnabled()
    dialog.generate_preview()
    dialog.apply_plan()
    assert session.dirty and not dialog.apply.isEnabled()
    session.undo()
    dialog.reject()
    assert not session.dirty
    dialog.deleteLater()
    app.processEvents()
