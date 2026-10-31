"""Independent staged object model/vertex animation editor."""
from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, QModelIndex
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QSlider, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QStyledItemDelegate, QStyleOptionViewItem)

from src.core.editing import EditSession
from src.core.model_editing import (AssetKey, ModelPlan, animation_document,
    asset_uses, clip_offsets, edit_mesh, encode_clip, import_animation,
    import_mesh_obj, plan_models, structures)
from src.core.object_models import AnimationClip, ModelInstance, ObjectLibrary, ObjectModel
from src.core.object_rebuild import compile_static
from src.core.exporter import export_object_obj
from src.core.objects import ObjectDefinition
from src.core.rom import AssetType, RomImage
from src.renderer.viewport import Viewport
from src.ui.material_panel import ROLE


class ModelDelegate(QStyledItemDelegate):
    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget | None:
        return super().createEditor(parent, option, index) if index.column() and index.data(ROLE+1) else None


class DraftSource(RomImage):
    def __init__(self, session: EditSession, drafts: dict[AssetKey, bytes]) -> None:
        rom = session.rom
        super().__init__(rom.data, rom.byte_order, rom.sections, rom.source_path)
        self.session, self.drafts = session, drafts

    def read_asset(self, asset_type: AssetType, index: int, *, decompress: bool = False) -> bytes:
        key = asset_type, index
        if key in self.drafts:
            if decompress:
                return self.drafts[key]
            from src.core.editing import compress_asset
            return compress_asset(self.drafts[key])
        return self.session.asset_source.read_asset(asset_type, index, decompress=decompress)

    def count(self, asset_type: AssetType) -> int:
        return self.session.asset_source.count(asset_type)


class ModelEditorDialog(QDialog):
    assets_changed = Signal()
    history_requested = Signal(bool)

    def __init__(self, session: EditSession, model_id: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session, self.current = session, model_id
        self.drafts: dict[AssetKey, bytes] = {}
        self.plan: ModelPlan | None = None
        self._loading = False
        self.library: ObjectLibrary | None = None
        self.setObjectName('objectModelEditor')
        self.setWindowTitle('Object Models & Animation')
        self.resize(1400, 930)
        root = QVBoxLayout(self)
        intro = QLabel('Shared assets affect every use of a model or clip. Static OBJ rebuilding supports added/extruded faces; '
            'animated models retain topology/groups and frame counts. '
            'OBJ export uses 1:100 scale; import restores ×100. Leave Blender import/export Scale at 1. '
            'Preview changes, then Apply.', self)
        intro.setWordWrap(True)
        root.addWidget(intro)
        split = QSplitter(self)
        root.addWidget(split, 1)
        left = QWidget(split)
        ll = QVBoxLayout(left)
        self.search = QLineEdit(left)
        self.search.setPlaceholderText('Filter model ID or object name…')
        ll.addWidget(self.search)
        self.list = QTreeWidget(left)
        self.list.setObjectName('objectModelList')
        self.list.setRootIsDecorated(False)
        self.list.setHeaderLabels(['ID', 'Shared object definitions'])
        self.list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.list.setColumnWidth(0, 65)
        ll.addWidget(self.list)
        right = QWidget(split)
        rl = QVBoxLayout(right)
        self.caption = QLabel(right)
        self.caption.setWordWrap(True)
        rl.addWidget(self.caption)
        vertical = QSplitter(Qt.Orientation.Vertical, right)
        rl.addWidget(vertical, 1)
        top = QWidget(vertical)
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        self.viewport = Viewport(top)
        self.viewport.setMinimumSize(400, 210)
        self.viewport.show_axes = True
        tl.addWidget(self.viewport, 1)
        bar = QHBoxLayout()
        tl.addLayout(bar)
        self.clip = QComboBox(top)
        self.clip.setObjectName('objectAnimationClip')
        bar.addWidget(self.clip)
        self.play = QCheckBox('Play', top)
        bar.addWidget(self.play)
        self.timeline = QSlider(Qt.Orientation.Horizontal, top)
        self.timeline.setObjectName('objectAnimationTimeline')
        bar.addWidget(self.timeline, 1)
        self.frame_label = QLabel(top)
        bar.addWidget(self.frame_label)
        fit = QPushButton('Fit (F)', top)
        fit.clicked.connect(self.viewport.reset_camera)
        bar.addWidget(fit)
        self.preview_textures = QCheckBox('Textures', top)
        self.preview_textures.setObjectName('objectPreviewTextures')
        self.preview_textures.setChecked(True)
        self.preview_textures.setToolTip('Turn off texture artwork to inspect the solid imported shape. Preview only.')
        self.preview_textures.toggled.connect(self.viewport.set_textured)
        bar.addWidget(self.preview_textures)
        wire = QCheckBox('Wireframe', top)
        wire.toggled.connect(self.viewport.set_wireframe)
        bar.addWidget(wire)
        self.tabs = QTabWidget(vertical)
        self.vertices = self._table(['Vertex', 'X', 'Y', 'Z', 'R', 'G', 'B', 'A'], 'Model vertices')
        self.uvs = self._table(['Face', 'U0', 'V0', 'U1', 'V1', 'U2', 'V2'], 'Face UVs (s10.5)')
        self.animation = self._table(['Group', 'Offset X', 'Offset Y', 'Offset Z'], 'Animation offsets')
        self.attachments = self._table(['Slot', 'Vertex'], 'Attachments')
        self.spheres = self._table(['Sphere', 'Vertex', 'Radius scale / 64'], 'Collision spheres')
        self.properties = self._table(['Property', 'Value'], 'Collision settings')
        self.uses = QPlainTextEdit(self.tabs)
        self.uses.setReadOnly(True)
        self.tabs.addTab(self.uses, 'Known uses / limits')
        self.budget = QPlainTextEdit(self.tabs)
        self.budget.setReadOnly(True)
        self.tabs.addTab(self.budget, 'Pending / ROM budget')
        mode_row = QHBoxLayout()
        rl.addLayout(mode_row)
        mode_row.addWidget(QLabel('OBJ import', right))
        self.obj_mode = QComboBox(right)
        self.obj_mode.setObjectName('objectObjImportMode')
        for i, label in enumerate(('Automatic (reshape / static rebuild)', 'Reshape positions only', 'Rebuild static topology')):
            self.obj_mode.addItem(label, i)
        self.obj_mode.setToolTip('Static rebuilding supports new/deleted/extruded faces, existing batch_N materials and UVs. '
            'Automatic first tries the fixed-topology position importer. Animated clips keep their topology.')
        mode_row.addWidget(self.obj_mode, 1)
        files = QHBoxLayout()
        rl.addLayout(files)
        self.export_obj = QPushButton('Export OBJ + artwork…', right)
        self.export_obj.setToolTip('Export the base mesh with batch materials, UVs, vertex colors and referenced PNG textures.')
        self.export_obj.clicked.connect(self._export_obj)
        self.import_obj = QPushButton('Import mesh OBJ…', right)
        self.import_obj.clicked.connect(self._import_obj)
        self.export_clip = QPushButton('Export clip JSON…', right)
        self.export_clip.clicked.connect(self._export_clip)
        self.import_clip = QPushButton('Import clip JSON…', right)
        self.import_clip.clicked.connect(self._import_clip)
        for button in (self.export_obj, self.import_obj, self.export_clip, self.import_clip):
            files.addWidget(button)
        restore = QHBoxLayout()
        rl.addLayout(restore)
        self.original = QPushButton('Restore original model + clips (draft)', right)
        self.original.clicked.connect(self._original)
        restore.addWidget(self.original)
        self.reset = QPushButton('Reset this model’s drafts', right)
        self.reset.clicked.connect(self._reset)
        restore.addWidget(self.reset)
        self.message = QLabel('Vertex coordinates are game units, Y up. Linked animation/smoothing vertices move together. '
            'Clip offsets are relative to the base mesh; final stored frame is an interpolation endpoint.', self)
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(self.message.fontMetrics().lineSpacing()*3)
        root.addWidget(self.message)
        bottom = QHBoxLayout()
        root.addLayout(bottom)
        self.undo = QPushButton('Undo project edit', self)
        self.undo.clicked.connect(lambda: self._history(False))
        self.redo = QPushButton('Redo project edit', self)
        self.redo.clicked.connect(lambda: self._history(True))
        bottom.addWidget(self.undo)
        bottom.addWidget(self.redo)
        bottom.addStretch(1)
        self.preview = QPushButton('Preview pending changes', self)
        self.preview.setObjectName('previewObjectModels')
        self.preview.clicked.connect(self.build_preview)
        bottom.addWidget(self.preview)
        self.apply = QPushButton('Apply pending assets', self)
        self.apply.setObjectName('applyObjectModels')
        self.apply.clicked.connect(self._apply)
        bottom.addWidget(self.apply)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.rejected.connect(self.reject)
        bottom.addWidget(close)
        split.setSizes([290, 1080])
        vertical.setSizes([350, 330])
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.play.toggled.connect(lambda on: self.timer.start() if on else self.timer.stop())
        self.search.textChanged.connect(self._filter)
        self.list.currentItemChanged.connect(self._selected)
        self.clip.currentIndexChanged.connect(self._clip_changed)
        self.timeline.valueChanged.connect(self._frame_changed)
        self.reload()

    def _table(self, columns: list[str], label: str) -> QTreeWidget:
        table = QTreeWidget(self.tabs)
        table.setObjectName('model'+label.split()[0])
        table.setRootIsDecorated(False)
        table.setHeaderLabels(columns)
        table.setItemDelegate(ModelDelegate(table))
        table.itemPressed.connect(lambda *_: self.play.setChecked(False))
        for column in range(len(columns)):
            table.setColumnWidth(column, 75 if column else 80)
        table.itemChanged.connect(lambda item, column, widget=table: self._edited(widget, item, column))
        self.tabs.addTab(table, label)
        return table

    def reload(self) -> None:
        self._loading = True
        self.list.clear()
        self.model_uses = asset_uses(self.session)
        for i in range(self.session.rom.count(AssetType.OBJECT_MODELS)):
            headers, _ = self.model_uses.get(i, ((), ()))
            names = ', '.join(self.session.database.definitions[h].name for h in headers)
            item = QTreeWidgetItem([str(i), names or '(compiled / unreferenced)'])
            item.setData(0, ROLE, i)
            self.list.addTopLevelItem(item)
            if i == self.current:
                self.list.setCurrentItem(item)
        self._loading = False
        self._load_model(fit=True)
        self._filter()
        self._invalidate()

    def _raw(self, key: AssetKey | None = None) -> bytes:
        key = key or (AssetType.OBJECT_MODELS, self.current)
        return self.drafts.get(key, self.session.current_asset(*key))

    def _clip_key(self) -> AssetKey | None:
        return (AssetType.OBJECT_ANIMATIONS, int(self.clip.currentData())) if self.clip.currentData() is not None and self.clip.currentData() >= 0 else None

    def _row(self, table: QTreeWidget, index: int, values: list[str], *, editable: tuple[int, ...] = ()) -> None:
        item = QTreeWidgetItem([str(index), *values])
        item.setData(0, ROLE, index)
        item.setData(0, ROLE+1, editable or tuple(range(1, len(values)+1)))
        for column in item.data(0, ROLE+1):
            item.setData(column, ROLE+1, True)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        table.addTopLevelItem(item)

    def _load_model(self, *, fit: bool = False) -> None:
        self._loading = True
        selected_clip = self.clip.currentData()
        self.library = ObjectLibrary(DraftSource(self.session, self.drafts))
        model = self.library.model(self.current)
        self.model = model
        self.caption.setText(f'Model {self.current} · {model.mesh.vertex_count} vertices · {model.mesh.triangle_count} faces · '
            f'{model.animated_count} animated groups · {len(model.raw_data):,} decoded bytes')
        self.viewport.hud.setText(f'Model {self.current} · shared asset preview\n'
            'RMB look · WASD fly · Q/E vertical · Shift boost\n'
            'Alt + RMB orbit · Wheel zoom · F fit · Esc release')
        self.viewport.hud.adjustSize()
        self.clip.clear()
        self.clip.addItem('Base mesh', -1)
        for i in range(self.library.clip_count(self.current)):
            aid = self.library.animation_ids[self.current]+i
            clip = self.library.clip(self.current, i)
            self.clip.addItem(f'Clip {i} · asset {aid} · {clip.frame_count} stored frames', aid)
        self.clip.setCurrentIndex(max(0, self.clip.findData(selected_clip)))
        for table in (self.vertices, self.uvs, self.attachments, self.spheres, self.properties):
            table.clear()
        baked: set[int] = set()
        seg = model.mesh.segments[0]
        for b, end in zip(seg.batches, (*seg.batches[1:], seg.terminal_batch)):
            if b.misc_data == 255 and not b.flags & 0x8000:
                baked.update(range(b.vertices_offset, end.vertices_offset))
        for i, (p, c) in enumerate(zip(seg.vertices, seg.colors)):
            self._row(self.vertices, i, [str(int(v)) for v in (*p, *c)], editable=tuple(range(1, 8)) if i in baked else (1, 2, 3))
        for i, uv in enumerate(seg.uvs):
            self._row(self.uvs, i, [str(int(v)) for v in uv.reshape(-1)])
        attaches, spheres = structures(model.raw_data)
        for i, value in enumerate(attaches):
            self._row(self.attachments, i, [str(value)])
        for i, pair in enumerate(spheres):
            self._row(self.spheres, i, list(map(str, pair)))
        self._row(self.properties, 0, [format(struct.unpack_from('>f', model.raw_data, 0x3C)[0], '.9g')])
        self.properties.topLevelItem(0).setText(0, 'Broad-phase distance')
        headers, levels = self.model_uses.get(self.current, ((), ()))
        self.uses.setPlainText('Shared object headers:\n'+('\n'.join(f'{h}: {self.session.database.definitions[h].name}' for h in headers) or 'None found')+
            '\n\nKnown affected levels, including actors / attachments / skyboxes:\n'+('\n'.join(levels) or 'None found')+
            '\n\nCompiled spawns/racers/menu code may add uses.\n\n'
            'OBJ Automatic import reshapes existing vertices first, then rebuilds changed static topology. '
            'Choose Rebuild static topology to import batch_N materials/UVs even when counts match. '
            'Existing texture assets remain fixed. Models with clips retain fixed topology. '
            'Use the Texture Browser for artwork pixels. Lit vertex bytes remain protected; baked RGBA and fixed-point UVs are editable here.\n\n'
            'Attachments reference existing vertices (their positions follow animation). Collision sphere radius in world units is '
            '(radius scale / 64) × placed object scale × 50. Broad-phase distance controls early collision rejection; it is not the sphere radius. '
            'These collision tests depend on object behavior.\n\n'
            'Animation uses signed16 first offsets and signed8 increments (-128..127) between keyframes, with integer sixteenth interpolation. '
            'Final stored frame is the interpolation endpoint. Root offsets, head-tilt controls and unknown frame header bytes are retained. '
            'Preview shows vertex deformation with neutral lighting, without game scripts, attachments or collision simulation.\n\n'
            'Static rebuilds report model/normal/instance/collision memory growth separately from ROM storage. '
            'Keep referenced vertex rows ordered for assemblies/collision spheres. New topology for animated clips or mixed matrix batches is unsupported. '
            'Scripted behavior and behavior-specific vertex references are not simulated in this preview.')
        self._loading = False
        self._clip_changed()
        self.viewport.bounds_min = np.array(model.mesh.bounds.minimum, np.float32)
        self.viewport.bounds_max = np.array(model.mesh.bounds.maximum, np.float32)
        if fit:
            self.viewport.reset_camera()

    def _selected(self, item: QTreeWidgetItem | None, *_: object) -> None:
        if self._loading or item is None:
            return
        self.play.setChecked(False)
        self.current = int(item.data(0, ROLE))
        self._load_model(fit=True)

    def _filter(self, *_: object) -> None:
        text = self.search.text().strip().casefold()
        for i in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(i)
            item.setHidden(text not in (' '.join(item.text(c) for c in range(2))).casefold())

    def _clip_changed(self, *_: object) -> None:
        if self._loading:
            return
        self._loading = True
        key = self._clip_key()
        self.export_clip.setEnabled(key is not None)
        self.import_clip.setEnabled(key is not None)
        self.play.setEnabled(key is not None)
        self.timeline.setEnabled(key is not None)
        if key is None:
            self.play.setChecked(False)
        frames = AnimationClip.from_bytes(self._raw(key), self.model).frame_count if key else 1
        self.timeline.setRange(0, max(0, (frames-1)*16))
        self._loading = False
        self._frame_changed()

    def _frame_changed(self, *_: object) -> None:
        if self._loading:
            return
        self._loading = True
        self.animation.clear()
        key = self._clip_key()
        frame16 = self.timeline.value()
        frame = frame16//16
        self.frame_label.setText(f'Frame {frame} + {frame16 % 16}/16')
        if key:
            clip = AnimationClip.from_bytes(self._raw(key), self.model)
            for i, p in enumerate(clip_offsets(clip, self.model)[frame]):
                self._row(self.animation, i, list(map(str, p)))
        definition = ObjectDefinition(0, 'Preview', 2, 1., model_type=0, model_ids=(self.current,))
        instance = ModelInstance(0, definition, self.current, (0., 0., 0.), 1., (0., 0., 0.),
            clip_index=self.clip.currentIndex()-1, sampled_frame=frame16 if key else None)
        self.viewport.set_model_instances(self.library, (instance,))
        self._loading = False

    def _tick(self) -> None:
        if self.timeline.maximum():
            self.timeline.setValue((self.timeline.value()+1) % self.timeline.maximum())

    def _set_draft(self, key: AssetKey, raw: bytes) -> None:
        if raw == self.session.current_asset(*key):
            self.drafts.pop(key, None)
        else:
            self.drafts[key] = raw
        self._invalidate()

    def _edited(self, table: QTreeWidget, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or column == 0:
            return
        try:
            if column not in item.data(0, ROLE+1):
                raise ValueError('Lit/environment normal bytes are protected')
            index = int(item.data(0, ROLE))
            if table is self.animation:
                key = self._clip_key()
                if key is None:
                    return
                offsets = clip_offsets(AnimationClip.from_bytes(self._raw(key), self.model), self.model).copy()
                offsets[self.timeline.value()//16, index] = [int(item.text(c)) for c in range(1, 4)]
                raw = encode_clip(self._raw(key), self.model, offsets)
            else:
                key = AssetType.OBJECT_MODELS, self.current
                if table is self.properties:
                    raw = edit_mesh(self._raw(key), 'distance', 0, float(item.text(1)))
                else:
                    kind, columns = ('vertex', range(1, 4)) if table is self.vertices and column <= 3 else (
                        ('color', range(4, 8)) if table is self.vertices else ('uv', range(1, 7)) if table is self.uvs else (
                        'attachment', range(1, 2)) if table is self.attachments else ('sphere', range(1, 3)))
                    raw = edit_mesh(self._raw(key), kind, index, [int(item.text(c)) for c in columns])
            self._set_draft(key, raw)
            self._load_model()
            restored = table.topLevelItem(index)
            if restored is not None:
                table.setCurrentItem(restored, column)
                table.scrollToItem(restored)
            self.message.setText('Draft updated. Review the animated preview and Known uses, then Preview pending changes → Apply.')
        except (ValueError, OverflowError) as error:
            self.message.setText(f'Edit rejected: {error}')
            self._load_model()

    def _invalidate(self) -> None:
        self.plan = None
        self.apply.setEnabled(False)
        self.preview.setEnabled(bool(self.drafts))
        self.undo.setEnabled(not self.drafts and self.session.can_undo)
        self.redo.setEnabled(not self.drafts and self.session.can_redo)
        self.budget.setPlainText('\n'.join(f'{s.name} {i}: {sum(a != b for a, b in zip(self.session.current_asset(s, i), raw))+abs(len(raw)-len(self.session.current_asset(s,i)))} changed/appended bytes'
            for (s, i), raw in sorted(self.drafts.items())) or 'No pending changes.')

    def build_preview(self) -> None:
        self.plan = None
        self.apply.setEnabled(False)
        try:
            self.plan = plan_models(self.session, self.drafts)
            self.budget.setPlainText(self.plan.report.to_text())
            self.tabs.setCurrentWidget(self.budget)
            self.apply.setEnabled(bool(self.plan.after))
            self.message.setText(f'{len(self.plan.after)} shared asset(s) ready. Review layout/resource growth and affected uses in the report. '
                'ROM layout and decompression checks passed. Review shared uses and runtime memory growth before applying.')
        except (ValueError, OSError) as error:
            self.message.setText(f'Preview rejected: {error}')

    def _apply(self) -> None:
        if self.plan is None:
            return
        try:
            self.session.apply_models(self.plan)
            self.drafts.clear()
            self.assets_changed.emit()
            self.reload()
            self.message.setText('Object models and animation applied. Ctrl+Z undoes the change.')
        except (ValueError, OSError) as error:
            self.message.setText(f'Apply rejected: {error}')
            self.apply.setEnabled(False)

    def _history(self, redo: bool) -> None:
        if not self.drafts:
            self.history_requested.emit(redo)
            self.reload()

    def _model_keys(self) -> tuple[AssetKey, ...]:
        assert self.library is not None
        return ((AssetType.OBJECT_MODELS, self.current), *((AssetType.OBJECT_ANIMATIONS, i)
            for i in range(self.library.animation_ids[self.current], self.library.animation_ids[self.current+1])))

    def _original(self) -> None:
        for key in self._model_keys():
            self._set_draft(key, self.session.original_asset(*key))
        self._load_model()

    def _reset(self) -> None:
        for key in self._model_keys():
            self.drafts.pop(key, None)
        self._invalidate()
        self._load_model()

    def _export_obj(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, 'Export object mesh and artwork', f'model_{self.current}.obj', 'Wavefront OBJ (*.obj)')
        if path:
            try:
                destination = Path(path)
                if not destination.suffix:
                    destination = destination.with_suffix('.obj')
                result = export_object_obj(self._raw(), destination, source=DraftSource(self.session, self.drafts), model_id=self.current)
                self.message.setText(f'Base mesh, MTL and {len(result.texture_paths)} PNG texture(s) exported at 1:100 scale. '
                    'Keep the OBJ, MTL and texture folder together. Blender Scale 1; keep vertex rows and batch_N names. '
                    'Animated meshes retain topology; clips export separately as JSON.')
            except (OSError, ValueError) as error:
                self.message.setText(str(error))

    def _import_obj(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Import object mesh', '', 'Wavefront OBJ (*.obj)')
        if path:
            try:
                file = Path(path)
                if file.stat().st_size > 8*1024*1024:
                    raise ValueError('OBJ exceeds 8 MiB')
                text = file.read_text(encoding='utf-8-sig')
                mode = self.obj_mode.currentData()
                compiled = None
                if mode == 2:
                    compiled = compile_static(self.session.rom, self.current, text, appearance=self._raw())
                    raw = compiled.raw
                else:
                    try:
                        raw = import_mesh_obj(self._raw(), text)
                    except ValueError:
                        if mode == 1:
                            raise
                        compiled = compile_static(self.session.rom, self.current, text, appearance=self._raw())
                        raw = compiled.raw
                self._set_draft((AssetType.OBJECT_MODELS, self.current), raw)
                self._load_model(fit=True)
                self.message.setText((f'Static rebuild staged: {compiled.input_vertices} input vertices, {compiled.triangles} stored triangles. '
                    +' '.join(compiled.warnings)) if compiled else 'Replacement mesh positions staged. Review the preview before Apply.')
            except (OSError, ValueError) as error:
                self.message.setText(f'Import rejected: {error}')

    def _export_clip(self) -> None:
        key = self._clip_key()
        if key is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export vertex animation', f'animation_{key[1]}.json', 'Animation JSON (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps(animation_document(self._raw(key), self.model), indent=2)+'\n', encoding='utf-8')
                self.message.setText('Clip exported with frame/group metadata and integer XYZ offsets.')
            except (OSError, ValueError) as error:
                self.message.setText(str(error))

    def _import_clip(self) -> None:
        key = self._clip_key()
        if key is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Replace existing vertex animation', '', 'Animation JSON (*.json)')
        if path:
            try:
                file = Path(path)
                if file.stat().st_size > 32*1024*1024:
                    raise ValueError('Animation JSON exceeds 32 MiB')
                raw = import_animation(self._raw(key), self.model, json.loads(file.read_text(encoding='utf-8-sig')))
                self._set_draft(key, raw)
                self._load_model()
                self.message.setText('Replacement clip staged. Review playback and Preview pending changes before Apply.')
            except (OSError, ValueError, RecursionError) as error:
                self.message.setText(f'Import rejected: {error}')
