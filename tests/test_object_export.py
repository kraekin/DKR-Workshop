"""Complete object artwork bundles, round trips, overlays and atomic failures."""
from pathlib import Path
import re

import numpy as np
from PIL import Image
import pytest

from src.core.editing import EditSession
from src.core.exporter import export_object_obj
from src.core.image_assets import read_png
from src.core.model_editing import edit_mesh, import_mesh_obj
from src.core.object_models import ObjectLibrary, ObjectModel
from src.core.object_rebuild import compile_static, rebuild_obj
from src.core.rom import AssetType, RomImage
from src.core.textures import model_uvs


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(Path(__file__).resolve().parents[1].glob('*.z64'))
    if not paths:
        pytest.skip('Local original Rev1 ROM absent')
    return RomImage.from_file(paths[0])


def test_all390_object_bundles_keep_rows_winding_rgba_and_import_identity(rom: RomImage, tmp_path: Path) -> None:
    library = ObjectLibrary(rom)
    for index in range(390):
        model = library.model(index)
        raw = model.raw_data
        output = tmp_path/str(index)
        output.mkdir()
        result = export_object_obj(raw, output/'model.obj', source=rom, model_id=index)
        text = result.path.read_text()
        lines = text.splitlines()
        vertices = np.asarray([[float(v) for v in line.split()[1:]] for line in lines if line.startswith('v ')])
        faces = np.asarray([[int(v.split('/')[0])-1 for v in line.split()[1:]] for line in lines if line.startswith('f ')])
        segment = model.mesh.segments[0]
        np.testing.assert_array_equal(np.rint(vertices[:, :3]*100), segment.vertices)
        np.testing.assert_array_equal(np.rint(vertices[:, 3:]*255), segment.colors)
        np.testing.assert_array_equal(faces, model.mesh.indices)
        assert import_mesh_obj(raw, text) == raw, index
        assert result.material_path is not None
        mtl = result.material_path.read_text()
        used = {line.split()[1] for line in lines if line.startswith('usemtl ')}
        defined = {line.split()[1] for line in mtl.splitlines() if line.startswith('newmtl ')}
        assert used == {f'batch_{i}' for i in range(len(segment.batches))}
        assert used <= defined
        for line in mtl.splitlines():
            if line.startswith('map_Kd '):
                assert (output/line.removeprefix('map_Kd ')).is_file()
        assert model.raw_data == raw


@pytest.mark.parametrize('index', (0, 240, 256, 260))
def test_exported_uvs_selected_frames_png_alpha_and_safe_names(rom: RomImage, tmp_path: Path, index: int) -> None:
    library = ObjectLibrary(rom)
    model = library.model(index)
    result = export_object_obj(model.raw_data, tmp_path/'Object artwork # ü.obj', source=rom, model_id=index)
    lines = result.path.read_text().splitlines()
    assert re.fullmatch(r'[A-Za-z0-9_.-]+', result.material_path.name)
    assert f'mtllib {result.material_path.name}' in lines
    actual = np.array([[float(v) for v in line.split()[1:]] for line in lines if line.startswith('vt ')])
    expected = model_uvs(model.mesh, library.textures, obj=True)
    seg = model.mesh.segments[0]
    for batch, end in zip(seg.batches, (*seg.batches[1:], seg.terminal_batch)):
        if batch.texture_index == 255:
            expected[batch.faces_offset:end.faces_offset] = seg.uvs[batch.faces_offset:end.faces_offset]/32
            expected[batch.faces_offset:end.faces_offset, :, 1] = 1-expected[batch.faces_offset:end.faces_offset, :, 1]
    np.testing.assert_allclose(actual, expected.reshape(-1, 2), atol=1e-7)
    mtl = result.material_path.read_text()
    for png in result.texture_paths:
        tid, frame = (int(png.stem.split('_')[i]) for i in (1, 3))
        pixels = library.textures[tid].frames[frame].pixels
        with Image.open(png) as image:
            np.testing.assert_array_equal(np.array(image), pixels)
            assert image.info['dkr-png-rows'] == 'stored'
        np.testing.assert_array_equal(read_png(png, (pixels.shape[1], pixels.shape[0]),
            asset_type=AssetType.TEXTURES_3D, flip_y=True), pixels)
        if np.any(pixels[..., 3] < 255):
            assert f'map_d -imfchan a {png.parent.name}/{png.name}' in mtl
    again = export_object_obj(model.raw_data, result.path, source=rom, model_id=index)
    assert result.texture_paths == again.texture_paths
    assert len(list(tmp_path.glob('*_textures_*'))) <= 1


def test_current_project_pixels_and_unapplied_model_draft_are_exported_without_edits(rom: RomImage, tmp_path: Path) -> None:
    session = EditSession(rom)
    raw = session.current_asset(AssetType.OBJECT_MODELS, 256)
    model = ObjectModel.from_bytes(raw)
    tid = model.mesh.textures[0].texture_id
    pixels = session.image_texture(AssetType.TEXTURES_3D, tid).frames[0].pixels.copy()
    pixels[:] = (0, 255, 0, 255)
    session.import_image(AssetType.TEXTURES_3D, tid, 0, pixels)
    p = model.mesh.segments[0].vertices[0].astype(int)
    draft = edit_mesh(raw, 'vertex', 0, tuple(p+(1, 0, 0)))
    signature = session._signature()
    result = export_object_obj(draft, tmp_path/'draft.obj', source=session.asset_source, model_id=256)
    assert import_mesh_obj(draft, result.path.read_text()) == draft
    with Image.open(next(p for p in result.texture_paths if p.name.startswith(f'texture_{tid}_frame_0'))) as image:
        np.testing.assert_array_equal(np.array(image), session.image_texture(AssetType.TEXTURES_3D, tid).frames[0].pixels)
    assert session._signature() == signature and session.current_asset(AssetType.OBJECT_MODELS, 256) != draft


@pytest.mark.parametrize('index', (0, 256, 260))
def test_static_bundle_rebuild_preserves_existing_appearance(rom: RomImage, tmp_path: Path, index: int) -> None:
    raw = rom.read_asset(AssetType.OBJECT_MODELS, index, decompress=True)
    result = export_object_obj(raw, tmp_path/'static.obj', source=rom, model_id=index)
    baseline = compile_static(rom, index, rebuild_obj(raw, rom))
    imported = compile_static(rom, index, result.path.read_text())
    assert imported.raw == baseline.raw


@pytest.mark.parametrize('failure', ('png', 'mtl', 'obj'))
def test_failed_publication_restores_prior_bundle(rom: RomImage, tmp_path: Path, monkeypatch, failure: str) -> None:
    raw = rom.read_asset(AssetType.OBJECT_MODELS, 256, decompress=True)
    obj = tmp_path/'model.obj'
    mtl = tmp_path/'model.mtl'
    obj.write_bytes(b'previous OBJ')
    mtl.write_bytes(b'previous MTL')
    original = Path.replace
    def replace(self: Path, target: Path) -> Path:
        if (failure == 'png' and Path(target).suffix == '.png' or
                failure == 'mtl' and Path(target) == mtl or failure == 'obj' and Path(target) == obj):
            raise PermissionError(f'locked {failure}')
        return original(self, target)
    monkeypatch.setattr(Path, 'replace', replace)
    with pytest.raises(PermissionError):
        export_object_obj(raw, obj, source=rom, model_id=256)
    assert obj.read_bytes() == b'previous OBJ' and mtl.read_bytes() == b'previous MTL'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['model.mtl', 'model.obj']


def test_invalid_input_does_not_touch_destination(rom: RomImage, tmp_path: Path) -> None:
    path = tmp_path/'model.obj'
    path.write_text('previous')
    with pytest.raises(ValueError):
        export_object_obj(b'bad', path, source=rom)
    assert path.read_text() == 'previous'
    with pytest.raises(ValueError, match='.obj'):
        export_object_obj(b'bad', tmp_path/'bad.z64', source=rom)


def test_manually_modified_png_is_not_overwritten(rom: RomImage, tmp_path: Path) -> None:
    raw = rom.read_asset(AssetType.OBJECT_MODELS, 256, decompress=True)
    result = export_object_obj(raw, tmp_path/'model.obj', source=rom, model_id=256)
    before = {p: p.read_bytes() for p in (result.path, result.material_path, *result.texture_paths)}
    png = result.texture_paths[0]
    png.write_bytes(b'user-edited sidecar')
    before[png] = png.read_bytes()
    with pytest.raises(ValueError, match='sidecar differs'):
        export_object_obj(raw, result.path, source=rom, model_id=256)
    assert all(path.read_bytes() == data for path, data in before.items())


def test_model_window_export_keeps_pending_drafts_and_project_history(rom: RomImage, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication
    from src.ui.model_editor import ModelEditorDialog
    app = QApplication.instance() or QApplication([])
    session = EditSession(rom)
    dialog = ModelEditorDialog(session, 256)
    try:
        raw = dialog._raw()
        model = ObjectModel.from_bytes(raw)
        p = model.mesh.segments[0].vertices[0].astype(int)
        draft = edit_mesh(raw, 'vertex', 0, tuple(p+(1, 0, 0)))
        dialog._set_draft((AssetType.OBJECT_MODELS, 256), draft)
        signature = session._signature()
        path = tmp_path/'model.obj'
        monkeypatch.setattr('src.ui.model_editor.QFileDialog.getSaveFileName', lambda *args: (str(path), ''))
        dialog._export_obj()
        assert 'MTL' in dialog.message.text() and 'PNG' in dialog.message.text()
        assert import_mesh_obj(draft, path.read_text()) == draft
        assert dialog._raw() == draft and dialog.drafts
        assert session._signature() == signature and not session.dirty
    finally:
        dialog.viewport._timer.stop()
        dialog.reject()
        dialog.deleteLater()
        app.processEvents()
