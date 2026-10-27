"""Staged OBJ/MTL/PNG track import with an independent, interactive GL preview."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import numpy as np

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QTabWidget, QGroupBox)

from src.core.editing import EditSession
from src.core.level_model import LevelModel
from src.core.objects import LevelObject, RacePath
from src.core.obj_units import GAME_UNITS_PER_OBJ_UNIT
from src.core.rom import AssetType
from src.core.textures import Texture, load_texture, TextureFormat
from src.core.track_artwork import (ObjMaterial, MaterialImage, TextureOptions, SIZES,
    FORMATS, ALPHA_MODES, read_obj_materials, read_png, default_options, build_texture, stage_artwork)
from src.core.track_import import (CompiledTrack, ImportOptions, ObjMesh,
    compile_obj, default_materials, read_obj)
from src.core.track_segments import CELL_SIZES, MAX_INPUT_FACES, SegmentedTrack, compile_segmented_obj
from src.core.materials import SURFACES, TextureReference
from src.renderer.viewport import Viewport


class TrackCompileWorker(QThread):
    def __init__(self, mesh: ObjMesh, template: bytes, appearance: bytes,
                 refs: tuple[TextureReference,...], materials: dict[str,int],
                 surfaces: dict[str,int], options: ImportOptions, mode: str, cell_size: int,
                 parent: QWidget, *, images: dict[str,MaterialImage] | None = None,
                 existing: dict[int,bytes] | None = None) -> None:
        super().__init__(parent)
        self.mesh,self.template,self.appearance=mesh,template,appearance
        self.refs,self.materials,self.surfaces=refs,materials,surfaces
        self.options,self.mode,self.cell_size=options,mode,cell_size
        self.result: CompiledTrack | None=None
        self.error=''
        self.images,self.existing=images or {},existing or {}
        self.additions: tuple[bytes,...]=()

    def run(self) -> None:
        try:
            appearance,materials,self.additions,refs=stage_artwork(self.appearance,self.refs,self.materials,self.images,self.existing)
            segmented=(self.mode=='Spatial segments' or (self.mode=='Automatic' and
                (len(self.mesh.faces)>499 or bool(self.surfaces)
                 or len(LevelModel.from_bytes(appearance).textures)!=len(LevelModel.from_bytes(self.template).textures))))
            if segmented:
                self.result=compile_segmented_obj(self.mesh,self.template,refs,materials,self.options,
                    appearance=appearance,surfaces=self.surfaces,cell_size=self.cell_size)
            else:
                if self.surfaces or self.images:
                    raise ValueError('Choose Automatic or Spatial segments for custom artwork/surface choices')
                self.result=compile_obj(self.mesh,self.template,refs,materials,self.options,appearance=appearance)
        except (ValueError,OSError) as error:
            self.error=str(error)


class TrackImportDialog(QDialog):
    def __init__(self, session: EditSession, model_id: int,
                 objects: tuple[LevelObject, ...] = (), parent: QWidget | None = None,
                 *, paths: tuple[RacePath, ...] = ()) -> None:
        super().__init__(parent)
        self.setObjectName('trackImportDialog')
        self.setWindowTitle('Import track — OBJ preview')
        self.resize(1230, 850)
        self.session, self.model_id = session, model_id
        self.mesh: ObjMesh | None = None
        self.compiled: CompiledTrack | None = None
        self.slots: dict[str, QComboBox] = {}
        self.surfaces: dict[str,QComboBox] = {}
        self.worker: TrackCompileWorker | None=None
        self._close_when_done=False
        self._material_loading=False
        self.image_specs: dict[str,MaterialImage]={}
        self.additions: tuple[bytes,...]=()
        self.sidecar_warnings: tuple[str,...]=()
        self.textures: dict[int, Texture] = {}
        self.current = session.track_model(model_id)
        layout = QVBoxLayout(self)
        uses = ', '.join(f'{level.name} (level {level.index})' for level in session._catalog.levels
                         if level.header.geometry_id == model_id)
        self.target_label = QLabel(f'Replaces geometry {model_id}: {uses or "no course header reference"}', self)
        self.target_label.setWordWrap(True)
        self.target_label.setObjectName('trackImportTarget')
        layout.addWidget(self.target_label)
        description = QLabel('Import a static replacement track. Automatic keeps small models in one segment and partitions larger meshes into spatial cells. '
            f'Y is up; 1 OBJ unit = {GAME_UNITS_PER_OBJ_UNIT:g} game units. Leave Blender import/export Scale at 1. '
            'MTL diffuse PNGs/colors become dedicated texture assets; '
            'review their N64 conversion on Materials, or choose an existing ROM slot.', self)
        description.setWordWrap(True)
        layout.addWidget(description)
        row = QHBoxLayout()
        self.path = QLineEdit(self)
        self.path.setReadOnly(True)
        self.path.setPlaceholderText('Choose an OBJ file…')
        row.addWidget(self.path, 1)
        self.choose = QPushButton('Open OBJ…', self)
        self.choose.clicked.connect(self._choose)
        row.addWidget(self.choose)
        layout.addLayout(row)
        split = QSplitter(self)
        layout.addWidget(split, 1)
        controls = QWidget(split)
        controls.setMaximumWidth(470)
        left = QVBoxLayout(controls)
        left.setContentsMargins(0, 0, 8, 0)
        self.controls=controls
        pages=QTabWidget(controls)
        left.addWidget(pages,1)
        geometry_page=QWidget(pages);geometry_layout=QVBoxLayout(geometry_page)
        material_page=QWidget(pages);material_layout=QVBoxLayout(material_page)
        pages.addTab(geometry_page,'Geometry');pages.addTab(material_page,'Materials')
        self.pages=pages
        transforms = QGridLayout()
        self.scale = QDoubleSpinBox(self)
        self.scale.setDecimals(6)
        self.scale.setRange(.000001, 1000000)
        self.scale.setValue(GAME_UNITS_PER_OBJ_UNIT)
        self.scale.setAccessibleName('OBJ import scale')
        self.scale.setToolTip('Actual OBJ-to-game multiplier, applied once before rounding. '
            f'Default {GAME_UNITS_PER_OBJ_UNIT:g} restores tracks exported by this editor.')
        transforms.addWidget(QLabel('Scale (OBJ → game)', self), 0, 0)
        transforms.addWidget(self.scale, 0, 1)
        self.offset: list[QDoubleSpinBox] = []
        for i, axis in enumerate('XYZ', 1):
            spin = QDoubleSpinBox(self)
            spin.setRange(-1000000, 1000000)
            spin.setDecimals(2)
            spin.setAccessibleName(f'OBJ import offset {axis}')
            self.offset.append(spin)
            spin.setToolTip('Translation in game units, added after scaling.')
            transforms.addWidget(QLabel('Offset '+axis+' (game units)', self), i, 0)
            transforms.addWidget(spin, i, 1)
            spin.valueChanged.connect(self.invalidate)
        self.scale.valueChanged.connect(self.invalidate)
        geometry_layout.addLayout(transforms)
        self.mode=QComboBox(self)
        self.mode.addItems(('Automatic','Single segment (≤499)','Spatial segments'))
        self.mode.setAccessibleName('Track import segmentation mode')
        self.mode.currentIndexChanged.connect(self.invalidate)
        geometry_layout.addWidget(self.mode)
        self.cell_size=QComboBox(self)
        self.cell_size.addItem('Automatic cell size',0)
        for size in CELL_SIZES:self.cell_size.addItem(f'{size} unit cells',size)
        self.cell_size.setAccessibleName('Track import spatial cell size')
        self.cell_size.currentIndexChanged.connect(self.invalidate)
        geometry_layout.addWidget(self.cell_size)
        self.reverse = QCheckBox('Reverse face winding', self)
        self.double_sided = QCheckBox('Draw both sides', self)
        for box in (self.reverse, self.double_sided):
            box.toggled.connect(self.invalidate)
            geometry_layout.addWidget(box)
        geometry_layout.addStretch(1)
        self.materials = QTreeWidget(self)
        self.materials.setHeaderLabels(('Material', 'Artwork / slot', 'Surface'))
        self.materials.setRootIsDecorated(False)
        self.materials.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.materials.currentItemChanged.connect(self._material_selected)
        material_layout.addWidget(self.materials,1)
        art=QGroupBox('Selected material — PNG / MTL color',self)
        material_layout.addWidget(art)
        form=QGridLayout(art)
        self.art_path=QLabel('',art);self.art_path.setWordWrap(True)
        form.addWidget(self.art_path,0,0,1,4)
        self.png_choose=QPushButton('Choose PNG…',art);self.png_choose.clicked.connect(self._choose_png)
        form.addWidget(self.png_choose,1,0,1,4)
        self.art_width=QComboBox(art);self.art_height=QComboBox(art)
        for widget in (self.art_width,self.art_height):
            for size in SIZES:widget.addItem(str(size),size)
            widget.currentIndexChanged.connect(self._image_options_changed)
        self.art_width.setAccessibleName('Import texture width');self.art_height.setAccessibleName('Import texture height')
        form.addWidget(QLabel('Width',art),2,0);form.addWidget(self.art_width,2,1)
        form.addWidget(QLabel('Height',art),2,2);form.addWidget(self.art_height,2,3)
        self.art_format=QComboBox(art)
        for fmt in FORMATS:self.art_format.addItem(fmt.name,int(fmt))
        self.art_alpha=QComboBox(art);self.art_alpha.addItems(ALPHA_MODES)
        self.art_format.setAccessibleName('Import texture format');self.art_alpha.setAccessibleName('Import texture alpha')
        for widget in (self.art_format,self.art_alpha):widget.currentIndexChanged.connect(self._image_options_changed)
        form.addWidget(self.art_format,3,0,1,2);form.addWidget(self.art_alpha,3,2,1,2)
        self.art_clamp_u=QCheckBox('Clamp U',art);self.art_clamp_v=QCheckBox('Clamp V',art)
        for box in (self.art_clamp_u,self.art_clamp_v):box.toggled.connect(self._image_options_changed)
        form.addWidget(self.art_clamp_u,4,0,1,2);form.addWidget(self.art_clamp_v,4,2,1,2)
        form.addWidget(QLabel('Source PNG',art),5,0,1,2);form.addWidget(QLabel('N64 result',art),5,2,1,2)
        self.source_image=QLabel(art);self.converted_image=QLabel(art)
        for column,label in ((0,self.source_image),(2,self.converted_image)):
            label.setFixedHeight(90);label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet('background: #111922; border: 1px solid #435263;')
            form.addWidget(label,6,column,1,2)
        self.art_details=QLabel(art);self.art_details.setWordWrap(True)
        form.addWidget(self.art_details,7,0,1,4)
        self.build = QPushButton('Build preview', self)
        self.build.setObjectName('buildTrackImportPreview')
        self.build.setEnabled(False)
        self.build.clicked.connect(self.build_preview)
        left.addWidget(self.build)
        self.overlay = QCheckBox('Show existing objects and racing lines', self)
        self.overlay.setChecked(True)
        self.overlay.toggled.connect(self._overlay)
        left.addWidget(self.overlay)
        self.message = QLabel('Open an OBJ to build a preview. No project changes occur until Apply.', self)
        self.message.setWordWrap(True)
        left.addWidget(self.message)
        right = QWidget(split)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.viewport = Viewport(right)
        self.viewport.set_catalog_caption('OBJ import preview', model_id)
        self.viewport.setMinimumSize(380, 260)
        self.viewport.set_objects(objects, paths)
        self._overlay(True)
        right_layout.addWidget(self.viewport, 2)
        self.report = QPlainTextEdit(right)
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(230)
        right_layout.addWidget(self.report, 1)
        split.setSizes([390, 800])
        uses = ', '.join(f'{l.index}: {l.name}' for l in session._catalog.levels if l.header.geometry_id == model_id)
        note = QLabel(f'Affects shared model {model_id}: {uses}\n'
            'Objects, checkpoints, AI paths, minimap and level settings keep their current values. '
            'Align them to your new road before racing. The report includes collision limits, visibility and memory usage; '
            'animated waves are configured separately.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        buttons.rejected.connect(self.reject)
        self.apply = QPushButton('Apply track import', self)
        self.apply.setObjectName('applyTrackImport')
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self._apply)
        buttons.addButton(self.apply, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)
        self.finished.connect(self._cleanup)

    def _overlay(self, enabled: bool) -> None:
        self.viewport.set_objects_visible(enabled)
        self.viewport.set_racelines_visible(enabled)

    def _cleanup(self, _: int) -> None:
        self.viewport._timer.stop()
        self.viewport._release_input()
        self.viewport.cleanup()

    def reject(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._close_when_done=True
            self.worker.requestInterruption()
            self.message.setText('Finishing the current compile before closing. No import will be applied.')
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.reject();event.ignore()
        else:
            super().closeEvent(event)

    def invalidate(self, *_: object) -> None:
        self.compiled = None
        self.additions=()
        self.apply.setEnabled(False)
        if self.mesh is not None:
            self.message.setText('Settings changed. Build preview again before applying.')

    def _choose(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, 'Import track OBJ', self.path.text() or str(Path.cwd()), 'Wavefront OBJ (*.obj)')
        if chosen:
            self.load_path(Path(chosen))

    def load_path(self, path: Path) -> None:
        if self.worker is not None and self.worker.isRunning():return
        self.invalidate()
        self.mesh = None
        self.build.setEnabled(False)
        self.materials.clear()
        self.slots.clear()
        self.surfaces.clear()
        self.image_specs.clear()
        self.path.setText(str(path))
        try:
            mesh = read_obj(path,max_faces=MAX_INPUT_FACES)
            if len(mesh.materials)>255:
                raise ValueError('The import editor supports at most 255 named materials')
            sidecars,self.sidecar_warnings=read_obj_materials(path)
            defaults = default_materials(mesh, self.current)
            pixel_count=0
            for name in mesh.materials:
                item = QTreeWidgetItem([name, ''])
                self.materials.addTopLevelItem(item)
                combo = QComboBox(self.materials)
                combo.setMinimumContentsLength(6)
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                for i, slot in enumerate(self.current.textures):
                    ref = self.session.material_references[slot.texture_id]
                    combo.addItem(f'{i}: {ref.label}', i)
                combo.setCurrentIndex(defaults[name])
                combo.addItem('New PNG / color',-1)
                material=sidecars.get(name,ObjMaterial(name))
                p=np.full((1,1,4),255,np.uint8)
                if material.image is not None:
                    try:
                        p=read_png(material.image)
                        pixel_count+=p.shape[0]*p.shape[1]
                        if pixel_count>16*1024*1024:raise ValueError('Material PNGs exceed the combined 16 megapixel import bound')
                    except (OSError,ValueError) as error:
                        p=np.full((1,1,4),255,np.uint8)
                        material=replace(material,problems=material.problems+(str(error),))
                self.image_specs[name]=MaterialImage(material,p,default_options(p,material),0)
                if name in sidecars:combo.setCurrentIndex(combo.findData(-1))
                combo.currentIndexChanged.connect(self.invalidate)
                combo.currentIndexChanged.connect(lambda _,row=item:self.materials.setCurrentItem(row))
                combo.currentIndexChanged.connect(self._material_selected)
                self.materials.setItemWidget(item, 1, combo)
                self.slots[name] = combo
                surface=QComboBox(self.materials)
                surface.setMinimumContentsLength(5)
                surface.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                surface.addItem('Default / road' if combo.currentData()==-1 else 'From slot',None)
                for i,label in enumerate(SURFACES):surface.addItem(label,i)
                surface.currentIndexChanged.connect(self.invalidate)
                surface.currentIndexChanged.connect(lambda _,row=item:self.materials.setCurrentItem(row))
                self.materials.setItemWidget(item,2,surface)
                self.surfaces[name]=surface
            self.mesh = mesh
            self.materials.setCurrentItem(self.materials.topLevelItem(0))
            if sidecars:self.pages.setCurrentIndex(1)
            self.build.setEnabled(True)
            self.build_preview()
        except (ValueError, OSError) as error:
            self._failure(error)

    def _failure(self, error: Exception) -> None:
        self.compiled = None
        self.apply.setEnabled(False)
        self.viewport.set_model(None)
        self.report.clear()
        self.message.setText(f'Import rejected: {error}')

    def build_preview(self) -> None:
        if self.worker is not None and self.worker.isRunning():return
        self.invalidate()
        if self.mesh is None:
            return
        options = ImportOptions(self.scale.value(), tuple(s.value() for s in self.offset),
                                self.reverse.isChecked(), self.double_sided.isChecked())
        images={name:replace(spec,surface=self.surfaces[name].currentData() if self.surfaces[name].currentData() is not None else 0)
            for name,spec in self.image_specs.items() if self.slots[name].currentData()==-1}
        self.worker=TrackCompileWorker(self.mesh,self.session.original_asset(AssetType.LEVEL_MODELS,self.model_id),
            self.current.raw_data,self.session.material_references,{name:c.currentData() for name,c in self.slots.items()},
            {name:c.currentData() for name,c in self.surfaces.items() if c.currentData() is not None},options,
            self.mode.currentText(),int(self.cell_size.currentData()),self,images=images,
            existing={self.session.rom.count(AssetType.TEXTURES_3D)+i:self.session.current_asset(AssetType.TEXTURES_3D,self.session.rom.count(AssetType.TEXTURES_3D)+i)
                for i in range(len(self.session.custom_textures))})
        self.controls.setEnabled(False);self.choose.setEnabled(False)
        self.message.setText('Building geometry, collision seams, BSP and resource checks… Cancel closes when this compile finishes.')
        self.worker.finished.connect(self._built)
        self.worker.start()

    def _built(self) -> None:
        self.controls.setEnabled(True);self.choose.setEnabled(True)
        if self._close_when_done:
            super().reject();return
        assert self.worker is not None
        if self.worker.error or self.worker.result is None:
            self._failure(ValueError(self.worker.error or 'Compiler did not return a track'));return
        try:
            result=self.worker.result
            additions=self.worker.additions
            report = self.session.preview_track_import(self.model_id, result.raw,textures=additions)
            model = LevelModel.from_bytes(result.raw, model_id=self.model_id)
            first=len(self.session.material_references)
            textures={index:Texture.from_bytes(additions[index-first],texture_id=index) if index>=first else load_texture(self.session.asset_source,index)
                for index in {t.texture_id for t in model.textures}}
            self.viewport.set_model(model, textures)
            self.viewport.set_catalog_caption('OBJ import preview',self.model_id)
            memory=sum(len(raw)+96 for raw in additions)
            artwork=f'\nDedicated artwork: {len(additions)} new asset(s), {sum(map(len,additions)):,} ROM bytes + table growth; {memory:,} B texture allocations if all new assets load.\n'
            artwork+='Dedicated artwork uses additional ROM and runtime memory. The 700-entry texture cache and scene heap are shared with objects and effects.\n'
            self.report.setPlainText(result.to_text()+artwork+'\n'.join(self.sidecar_warnings)+'\n\n'+report.to_text())
            self.message.setText('Preview ready. RMB + WASD to inspect, F to fit. Apply stores one undo step.')
            self.compiled = result
            self.additions=additions
            self.apply.setEnabled(True)
        except (ValueError, OSError) as error:
            self._failure(error)

    def _apply(self) -> None:
        if self.compiled is None:
            return
        try:
            self.session.import_track(self.model_id, self.compiled.raw,textures=self.additions)
            self.accept()
        except (ValueError, OSError) as error:
            self._failure(error)

    def _selected_name(self) -> str | None:
        item=self.materials.currentItem()
        return item.text(0) if item is not None else None

    def _material_selected(self, *_: object) -> None:
        name=self._selected_name()
        if name not in self.image_specs:return
        spec=self.image_specs[name];opt=spec.options
        self.surfaces[name].setItemText(0,'Default / road' if self.slots[name].currentData()==-1 else 'From slot')
        self._material_loading=True
        for widget,value in ((self.art_width,opt.width),(self.art_height,opt.height),(self.art_format,int(opt.format))):
            widget.setCurrentIndex(widget.findData(value))
        self.art_alpha.setCurrentText(opt.alpha)
        self.art_clamp_u.setChecked(opt.clamp_u);self.art_clamp_v.setChecked(opt.clamp_v)
        self._material_loading=False
        self._draw_artwork()

    def _image_options_changed(self, *_: object) -> None:
        if self._material_loading:return
        name=self._selected_name()
        if name not in self.image_specs:return
        opt=TextureOptions(int(self.art_width.currentData()),int(self.art_height.currentData()),TextureFormat(self.art_format.currentData()),
            self.art_alpha.currentText(),self.art_clamp_u.isChecked(),self.art_clamp_v.isChecked())
        self.image_specs[name]=replace(self.image_specs[name],options=opt)
        self.invalidate();self._draw_artwork()

    def _draw_artwork(self) -> None:
        name=self._selected_name()
        if name not in self.image_specs:return
        spec=self.image_specs[name]
        self.art_path.setText(str(spec.material.image) if spec.material.image else 'Solid MTL diffuse color (or choose a PNG)')
        self.art_path.setToolTip(self.art_path.text())
        self.source_image.clear();self.converted_image.clear()
        def show(label: QLabel,p: np.ndarray) -> None:
            pixels=np.ascontiguousarray(p)
            q=QImage(pixels.data,pixels.shape[1],pixels.shape[0],pixels.strides[0],QImage.Format.Format_RGBA8888).copy()
            label.setPixmap(QPixmap.fromImage(q).scaled(170,86,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.FastTransformation))
        show(self.source_image,spec.pixels)
        try:
            if spec.material.problems:raise ValueError('; '.join(spec.material.problems))
            raw=build_texture(spec.pixels,spec.options,diffuse=spec.material.diffuse,opacity=spec.material.opacity)
            show(self.converted_image,Texture.from_bytes(raw).frames[0].pixels)
            status='New dedicated asset' if self.slots[name].currentData()==-1 else 'Existing ROM slot selected; PNG options are not applied'
            self.art_details.setText(f'{status}. {len(raw):,} ROM bytes; {len(raw)+96:,} B texture allocation. Kd/opacity baked into PNG; nearest-neighbor resize.')
        except ValueError as error:self.art_details.setText(str(error))

    def _choose_png(self) -> None:
        name=self._selected_name()
        if name not in self.image_specs:return
        chosen,_=QFileDialog.getOpenFileName(self,'Choose material PNG',str(Path(self.path.text()).parent),'PNG (*.png)')
        if not chosen:return
        try:
            p=read_png(Path(chosen))
            if p.shape[0]*p.shape[1]+sum(s.pixels.shape[0]*s.pixels.shape[1] for key,s in self.image_specs.items() if key!=name)>16*1024*1024:
                raise ValueError('Material PNGs exceed the combined 16 megapixel import bound')
            material=replace(self.image_specs[name].material,image=Path(chosen),problems=(),alpha_image=None)
            self.image_specs[name]=MaterialImage(material,p,default_options(p,material),0)
            self.slots[name].setCurrentIndex(self.slots[name].findData(-1))
            self.invalidate();self._material_selected()
        except (OSError,ValueError) as error:self.art_details.setText(f'PNG rejected: {error}')
