"""Catalog coverage, current-project artwork and unchanged placement semantics."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.core.editing import EditSession
from src.core.object_catalog import CatalogArtwork, CatalogLibrary, template_object
from src.core.object_structure import ObjectTemplate
from src.core.rom import AssetType, RomImage
from src.ui.object_palette import ObjectPalette


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(Path(__file__).resolve().parents[1].glob('*.z64'))
    if not paths:
        pytest.skip('Local original Rev1 ROM absent')
    return RomImage.from_file(paths[0])


def test_all_catalog_artwork_and_template_bytes_are_read_only(rom: RomImage) -> None:
    session = EditSession(rom)
    signature = session._signature()
    library = CatalogLibrary(session.asset_source)
    assert len(session.object_catalog) == 304
    for template in session.object_catalog:
        obj = template_object(session, template)
        assert obj.raw_data == template.raw(session)
        assert obj.object_id == template.object_id
        artwork = library.artwork(obj)
        pixels = library.thumbnail(artwork)
        assert pixels is not None and pixels.shape == (96, 96, 4)
        assert pixels.dtype == np.uint8 and pixels[..., 3].any(), obj.definition.name
    assert session._signature() == signature and not session.dirty


def test_catalog_reads_current_png_overlays(rom: RomImage) -> None:
    session = EditSession(rom)
    template = next(t for t in session.object_catalog if session.database.resolve(t.object_id).model_type == 4)
    obj = template_object(session, template)
    reference = obj.definition.model_ids[0]
    section = AssetType.TEXTURES_3D if reference & 0x8000 else AssetType.TEXTURES_2D
    index = reference & 0x7FFF
    pixels = session.image_texture(section, index).frames[0].pixels.copy()
    pixels[:] = (255, 0, 0, 255)
    session.import_image(section, index, 0, pixels)
    artwork = CatalogLibrary(session.asset_source).artwork(obj)
    np.testing.assert_array_equal(artwork.pixels, session.image_texture(section, index).frames[0].pixels)


def test_empty_unsupported_and_out_of_range_variant_do_not_block_objects(rom: RomImage) -> None:
    session = EditSession(rom)
    obj = template_object(session, session.object_catalog[0])
    library = CatalogLibrary(session.asset_source)
    empty = library.artwork(replace(obj, definition=replace(obj.definition, model_ids=())))
    assert empty.model is None and library.thumbnail(empty) is None
    unknown = library.artwork(replace(obj, definition=replace(obj.definition, model_type=3)))
    assert unknown.model is None and unknown.pixels is None
    assert 'Runtime' in unknown.label
    with pytest.raises(ValueError):
        library.thumbnail(CatalogArtwork('Empty', ''), 512)


@pytest.fixture
def palette(rom: RomImage):
    app = QApplication.instance() or QApplication([])
    session = EditSession(rom)
    dialog = ObjectPalette(session, 5, (123, -45, 678))
    yield dialog
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def test_visual_search_category_empty_state_and_no_mutations(palette: ObjectPalette) -> None:
    signature = palette.session._signature()
    assert palette.list.count() == 304 and palette.add_button.isEnabled()
    palette.search.setText('RubberTree')
    assert palette.title.text() == 'RubberTree'
    assert palette.add_button.isEnabled()
    assert palette.position() == (123, -45, 678)
    palette.category.setCurrentIndex(palette.category.findData('Checkpoints'))
    assert not palette.add_button.isEnabled() and palette.list.currentItem() is None
    assert palette.viewport.model_instances == ()
    palette.search.clear()
    visible = [palette.list.item(i) for i in range(palette.list.count()) if not palette.list.item(i).isHidden()]
    assert visible and all(palette.objects[i.data(Qt.ItemDataRole.UserRole).object_id].category == 'Checkpoints' for i in visible)
    palette.search.setText('nothing matches this catalog')
    assert not palette.add_button.isEnabled()
    palette.category.setCurrentIndex(0)
    palette.search.clear()
    assert palette.add_button.isEnabled()
    assert palette.session._signature() == signature and not palette.session.dirty


def test_preferred_zero_modes_add_undo_and_timer_cleanup(palette: ObjectPalette) -> None:
    palette.search.setText('RubberTree')
    preferred = palette.template()
    assert preferred.map_id is not None
    palette.template_mode.setCurrentIndex(1)
    assert palette.template() == ObjectTemplate(preferred.object_id)
    assert palette.template().raw(palette.session)[8:] == bytes(len(preferred.raw(palette.session))-8)
    palette.template_mode.setCurrentIndex(0)
    assert palette.template() == preferred
    key = palette.session.add_object(int(palette.map.currentData()), palette.template(), palette.position())
    assert palette.session.object(key).position == palette.position()
    assert palette.session.object(key).raw_data[8:] == preferred.raw(palette.session)[8:]
    palette.session.undo()
    assert not palette.session.dirty
    palette.reject()
    assert not palette._thumbnail_timer.isActive() and not palette.viewport._timer.isActive()
