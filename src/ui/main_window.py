"""ROM/decomp catalog loading and the reference viewport shell."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import sys

from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QDesktopServices
from PySide6.QtWidgets import QApplication, QDockWidget, QFileDialog, QLabel, QMainWindow, QMessageBox, QStatusBar

from src import __version__
from src.ui.deferred_edits import flush_edits
from src.core.level_header import LevelCatalog, LevelEntry, load_level_catalog
from src.core.rom import DecompAssets, RomImage, AssetType
from src.core.level_model import LevelModel, ModelError, load_level_model
from src.core.exporter import ExportResult, export_obj
from src.core.editing import EditSession, EditError, ObjectKey
from src.core.textures import Texture, SpriteAsset, SpriteInstance, load_model_textures, load_level_sprites
from src.core.objects import ObjectDatabase, ObjectMap, LevelObject, load_object_database, load_object_map, build_race_paths
from src.core.object_models import ObjectLibrary, model_instances, animation_sprites
from src.core.special_art import SpecialLibrary

from src.renderer.viewport import Viewport
from src.ui.level_panel import LevelPanel
from src.ui.object_inspector import ObjectInspector
from src.ui.toolbar import AnimationToolbar, CameraToolbar, RenderToolbar, SpecialArtworkToolbar, EnvironmentToolbar
from src.core.environment import WaveSettings, scroll_rates, water_preview
from src.core.cinematics import build_tracks, CinematicTimeline
from src.core.structure import audit_session
from src.core.textures import load_texture
from src.ui.export_report import ExportReportDialog
from src.core.routes import lane_entry, connection_entry
from src.core.research import compare_sessions
from src.ui.research_panel import ComparisonDialog
from src.core.materials import MaterialEdit
from src.core.geometry import (VertexKey, Position, geometry_profile, geometry_changed,
    linked_vertices, selection_center, move_vertices, copy_geometry)
from src.core.minimap import copy_minimap, sprite_references
from src.core.image_assets import IMAGE_SECTIONS, png_flip_default
from src.ui.image_browser import ImageBrowser
from src.ui.object_palette import ObjectPalette
from src.ui.track_rebuild_dialog import TrackRebuildDialog
from src.ui.track_import_dialog import TrackImportDialog
from src.ui.course_builder import CourseBuilder
from src.ui.course_names import CourseNamesDialog
from src.ui.global_objects import GlobalObjectsDialog
from src.ui.model_editor import ModelEditorDialog
from src.core.track_segments import collision_helper_faces
import numpy as np
from src.core.placement import (TerrainSurface, patch_entry, translated_entries, aligned_entries,
                                rotated_entries, scaled_entries, shared_parameter_entries, rotation_axes, can_scale)

from src.ui.about_window import AboutDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dkrMainWindow")
        self.catalog: LevelCatalog | None = None
        self.selected_level: LevelEntry | None = None
        self.current_model: LevelModel | None = None
        self.current_textures: dict[int, Texture] = {}
        self._texture_cache: dict[int, Texture] = {}
        self._model_cache: dict[int, LevelModel] = {}
        self.object_database: ObjectDatabase | None = None
        self._object_map_cache: dict[int, ObjectMap] = {}
        self.current_objects: tuple[LevelObject,...] = ()
        self.edit_session: EditSession | None = None
        self.image_browser: ImageBrowser | None = None
        self.current_sprites: tuple[SpriteInstance, ...] = ()
        self._sprite_cache: dict[int, SpriteAsset] = {}
        self._sprite_texture_cache: dict[int, Texture] = {}
        self.object_library: ObjectLibrary | None = None
        self.special_library: SpecialLibrary | None = None
        self._preview_selection: tuple[int,int] | None = None
        self._saved_preview_fov: float | None = None
        self._drag_objects: tuple[LevelObject, ...] = ()
        self._copied_position: tuple[int, int, int] | None = None
        self._terrain_cache: tuple[LevelModel, int, TerrainSurface] | None = None
        self._lane_drag = -1
        self._connection_source: ObjectKey | None = None
        self._geometry_gesture: tuple[int, bytes, tuple[VertexKey, ...], Position] | None = None
        self._geometry_preview_raw: bytes | None = None
        self._last_directory = Path.cwd()
        self.setWindowTitle(f"DKR Workshop - v{__version__}[*]")
        self.resize(1440, 900)
        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)
        self.level_panel = LevelPanel(self)
        self.object_inspector = ObjectInspector(self)
        self.level_dock = self._dock("Levels", "levelDock", self.level_panel, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.inspector_dock = self._dock(
            "Level / Object Inspector", "objectInspectorDock", self.object_inspector, Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.resizeDocks([self.level_dock, self.inspector_dock], [330, 330], Qt.Orientation.Horizontal)
        self.level_panel.level_selected.connect(self._select_level)
        self.toolbar = RenderToolbar(self)
        self.addToolBar(self.toolbar)
        self.camera_toolbar = CameraToolbar(self)
        self.addToolBarBreak()
        self.addToolBar(self.camera_toolbar)
        self.camera_toolbar.speed_changed.connect(self.viewport.set_camera_speed)
        self.camera_toolbar.view.currentTextChanged.connect(self.viewport.set_view)
        self.camera_toolbar.transform.currentTextChanged.connect(self.viewport.set_transform_mode)
        self.object_inspector.selection_changed.connect(self._select_group)
        self.object_inspector.placement.operation.connect(self._placement_operation)
        self.object_inspector.placement.grid.toggled.connect(lambda value: setattr(self.viewport, "grid_snap", value))
        self.object_inspector.routes.selected.connect(self._select_route)
        self.object_inspector.routes.parameter_changed.connect(self._route_parameter)
        self.object_inspector.routes.connection_changed.connect(self._route_connection)
        self.object_inspector.routes.preview_changed.connect(self._route_preview)
        self.object_inspector.routes.pick_requested.connect(self._pick_connection)
        self.object_inspector.routes.build_requested.connect(self._show_course_builder)
        self.object_inspector.tools.currentChanged.connect(self._route_preview)
        self.object_inspector.tabs.currentChanged.connect(self._route_preview)
        self.object_inspector.materials.edit_requested.connect(self._edit_materials)
        self.object_inspector.materials.image_requested.connect(lambda index: self._open_image_browser(AssetType.TEXTURES_3D, index))
        self.object_inspector.minimap.edit_requested.connect(self._edit_minimap)
        self.object_inspector.minimap.revert_requested.connect(self._revert_minimap)
        self.object_inspector.minimap.image_requested.connect(lambda index: self._open_image_browser(AssetType.SPRITES, index))
        self.object_inspector.materials.revert_requested.connect(self._revert_materials)
        self.object_inspector.materials.selection_changed.connect(self._material_preview)
        self.object_inspector.materials.preview_changed.connect(self._preview_materials)
        self.object_inspector.materials.prepare_edit.connect(self._commit_editor)
        self.object_inspector.materials.focus_requested.connect(self._focus_batch)
        self.object_inspector.geometry_tabs.currentChanged.connect(self._material_preview)
        self.object_inspector.tools.currentChanged.connect(self._material_preview)
        self.object_inspector.tabs.currentChanged.connect(self._material_preview)
        self.viewport.track_face_picked.connect(self.object_inspector.materials.pick_face)
        self.object_inspector.geometry_panel.selection_changed.connect(self._material_preview)
        self.object_inspector.geometry_panel.move_requested.connect(self._edit_geometry)
        self.object_inspector.geometry_panel.revert_requested.connect(self._revert_geometry)
        self.object_inspector.geometry_panel.focus_requested.connect(self._focus_geometry)
        self.object_inspector.geometry_panel.material_requested.connect(self._show_face_material)
        self.object_inspector.geometry_panel.rebuild_requested.connect(self._show_stock_rebuild)
        self.object_inspector.geometry_panel.import_requested.connect(self._show_track_import)
        self.object_inspector.geometry_panel.stock_requested.connect(self._restore_stock_track)
        self.viewport.geometry_picked.connect(self.object_inspector.geometry_panel.pick_item)
        self.viewport.geometry_drag_started.connect(self._geometry_drag_start)
        self.viewport.geometry_drag_preview.connect(self._geometry_drag_preview)
        self.viewport.geometry_drag_finished.connect(self._geometry_drag_finish)
        self.viewport.route_lane_selected.connect(self.object_inspector.routes.lane.setCurrentIndex)
        self.viewport.route_target_picked.connect(self._connection_picked)
        self.object_inspector.research.note_changed.connect(self._research_note)
        self.object_inspector.research.experiment_changed.connect(self._experiment_name)
        self.object_inspector.research.compare_requested.connect(self._compare_experiment)
        self.animation_toolbar = AnimationToolbar(self)
        self.addToolBarBreak()
        self.addToolBar(self.animation_toolbar)
        self.animation_toolbar.models.toggled.connect(self.viewport.set_models_visible)
        self.animation_toolbar.play.toggled.connect(lambda value:setattr(self.viewport,'preview_playing',value))
        self.animation_toolbar.time.valueChanged.connect(lambda value:self.viewport.set_preview_time(value/60))
        self.animation_toolbar.reset.triggered.connect(lambda:self.viewport.set_preview_time(0.0))
        self.animation_toolbar.rate.currentIndexChanged.connect(lambda:setattr(self.viewport,'preview_rate',float(self.animation_toolbar.rate.currentData())))
        self.viewport.preview_time_changed.connect(self.animation_toolbar.set_time)
        self.animation_toolbar.channel.currentIndexChanged.connect(self._preview_channel_changed)
        self.animation_toolbar.clip.currentIndexChanged.connect(self._preview_clip_changed)
        self.special_toolbar = SpecialArtworkToolbar(self)
        self.addToolBarBreak()
        self.addToolBar(self.special_toolbar)
        self.special_toolbar.visible.toggled.connect(self.viewport.set_special_visible)
        self.special_toolbar.portrait.currentIndexChanged.connect(self._update_special_artwork)
        self.environment_toolbar = EnvironmentToolbar(self)
        self.addToolBar(self.environment_toolbar)
        for action_name, attribute in (('sky', 'preview_sky'), ('fog', 'preview_fog'),
                                       ('motion', 'preview_texture_motion'), ('water', 'preview_water'),
                                       ('gradient', 'preview_gradient')):
            action = getattr(self.environment_toolbar, action_name)
            action.toggled.connect(lambda checked, name=attribute: (setattr(self.viewport, name, checked), self.viewport.update()))
        self._environment_key: object = None
        self._cinematic_key: object = None
        cinema = self.object_inspector.cinematics
        cinema.node_selected.connect(self._select_route)
        cinema.parameter_changed.connect(self._cinematic_parameter)
        cinema.time_requested.connect(self.viewport.set_preview_time)
        cinema.duration_changed.connect(self._cinematic_duration)
        cinema.camera_requested.connect(self.viewport.set_cinematic_camera)
        cinema.paths_changed.connect(lambda value: (setattr(self.viewport, 'show_cinematic_paths', value), self.viewport.update()))
        cinema.motion_changed.connect(lambda value: (setattr(self.viewport, 'cinematic_motion', value), self.viewport.set_preview_time(self.viewport.preview_time)))
        self.viewport.preview_time_changed.connect(cinema.set_time)
        self.viewport.cinematic_camera_released.connect(lambda: cinema.camera.setChecked(False))
        self.toolbar.grid.toggled.connect(self.viewport.set_grid_visible)
        self.toolbar.grid_auto.toggled.connect(self.viewport.set_grid_automatic)
        self.toolbar.grid_follow.toggled.connect(self.viewport.set_grid_follow_selection)
        self.toolbar.grid_pick.triggered.connect(self.viewport.begin_grid_placement)
        self.toolbar.grid_reset.triggered.connect(self.viewport.reset_grid_plane)
        self.viewport.grid_changed.connect(self._sync_grid_controls)
        self.viewport.grid_follow_changed.connect(self._sync_grid_follow)
        self.toolbar.axes.toggled.connect(self.viewport.set_axes_visible)
        self.toolbar.fit.triggered.connect(self.viewport.reset_camera)
        self.toolbar.wireframe.toggled.connect(self.viewport.set_wireframe)
        self.toolbar.vertex_colors.toggled.connect(self.viewport.set_vertex_colors)
        self.toolbar.bounds.toggled.connect(self.viewport.set_segment_bounds_visible)
        self.toolbar.culling.toggled.connect(self.viewport.set_backface_culling)
        self.toolbar.segment_selected.connect(self._select_segment)
        self.toolbar.isolate.toggled.connect(self.viewport.set_segment_isolated)
        self.toolbar.textures.toggled.connect(self.viewport.set_textured)
        self.toolbar.sprites.toggled.connect(self.viewport.set_sprites_visible)
        self.toolbar.objects.toggled.connect(self.viewport.set_objects_visible)
        self.toolbar.racelines.toggled.connect(self.viewport.set_racelines_visible)
        self.toolbar.routes_changed.connect(self._update_routes)
        self.viewport.object_selected.connect(self._select_picked_object)
        self.viewport.object_selected.connect(lambda index: self._update_edit_actions())
        self.object_inspector.object_selected.connect(self.viewport.select_object)
        self.object_inspector.object_selected.connect(lambda index: self._update_edit_actions())
        self.object_inspector.object_selected.connect(self._preview_selection_changed)
        self.viewport.object_selected.connect(self._preview_selection_changed)
        self.object_inspector.object_focused.connect(self._focus_object)
        self.object_inspector.visible_objects_changed.connect(self.viewport.set_visible_objects)
        self.object_inspector.edit_requested.connect(self._apply_edit)
        self.object_inspector.level_settings.edit_requested.connect(self._apply_level_setting)
        self.object_inspector.level_settings.revert_requested.connect(self._revert_level_settings)
        self.object_inspector.level_settings.preview_changed.connect(self._set_level_fov_preview)
        self.object_inspector.nudge_requested.connect(self._nudge_selected)
        self.object_inspector.move_mode_changed.connect(self.viewport.set_object_move_mode)
        self.object_inspector.move_step_changed.connect(self.viewport.set_object_move_step)
        self.object_inspector.mouse_move_changed.connect(self.viewport.set_mouse_move_enabled)
        self.viewport.prepare_pointer_selection.connect(self._commit_editor)
        self.viewport.object_drag_started.connect(self._begin_mouse_move)
        self.viewport.object_drag_preview.connect(self._preview_mouse_move)
        self.viewport.transform_drag_preview.connect(self._preview_transform)
        self.viewport.object_drag_finished.connect(self._finish_mouse_move)
        self.object_inspector.revert_requested.connect(self._revert_selected)
        self.object_inspector.add_requested.connect(self._add_object)
        self.object_inspector.duplicate_requested.connect(self._duplicate_objects)
        self.object_inspector.delete_requested.connect(self._delete_objects)
        self.viewport.object_nudged.connect(self._nudge_object)
        self._create_menus()
        status = QStatusBar(self)
        self.setStatusBar(status)
        self.viewport.render_failed.connect(self._show_render_error)
        self._gpu_label = QLabel("GPU: initializing", self)
        self._gpu_label.setToolTip("Help → Graphics / GPU shows the active OpenGL driver and Windows GPU selection instructions.")
        status.addPermanentWidget(self._gpu_label)
        self._telemetry_label = QLabel("", self)
        status.addPermanentWidget(self._telemetry_label)
        self._budget_label = QLabel("", self)
        self._budget_label.setToolTip("File → ROM budget and project changes shows the exact export layout and shared level uses.")
        status.addPermanentWidget(self._budget_label)
        self.viewport.status_changed.connect(self._update_gpu_label)
        status.showMessage("Initializing OpenGL 3.3 Core…")
        self._update_edit_actions()

    def _dock(self, title: str, name: str, widget: LevelPanel | ObjectInspector,
              area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        dock.setMinimumWidth(210)
        self.addDockWidget(area, dock)
        return dock

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.open_rom_action = QAction("Open &ROM…", self)
        self.open_rom_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_rom_action.setStatusTip("Open Diddy Kong Racing USA Rev 1 (.z64, .v64 or .n64)")
        self.open_rom_action.triggered.connect(self._choose_rom)
        #self.decomp_action = QAction("Set &Decomp Directory…", self)
        #self.decomp_action.setStatusTip("Read an extracted us.v80 assets.meta.json catalog")
        #self.decomp_action.triggered.connect(self._choose_decomp)
        self.export_action = QAction("Export Wavefront .&OBJ…", self)
        self.export_action.setEnabled(False)
        self.export_action.setStatusTip("Export all track segments with vertex RGB, UVs, MTL and PNG textures")
        self.export_action.triggered.connect(self._choose_export)
        file_menu.addActions([self.open_rom_action, self.export_action])
        self.image_browser_action = QAction("Texture & Sprite Browser / PNG…", self)
        self.image_browser_action.triggered.connect(lambda: self._open_image_browser())
        self.image_browser_action.setEnabled(False)
        self.course_names_action=QAction('Course &Names…',self)
        self.course_names_action.setObjectName('openCourseNames')
        self.course_names_action.setStatusTip('Edit course names in a separate window; preview and apply changes to the project')
        self.course_names_action.triggered.connect(self._show_course_names)
        self.global_objects_action = QAction('Global Object Properties…', self)
        self.global_objects_action.setObjectName('openGlobalObjectProperties')
        self.global_objects_action.triggered.connect(self._show_global_objects)
        self.model_editor_action = QAction('Object Models && Animation…', self)
        self.model_editor_action.setObjectName('openObjectModels')
        self.model_editor_action.triggered.connect(self._show_model_editor)
        self.course_builder_action = QAction('Course Builder…', self)
        self.course_builder_action.setObjectName('openCourseBuilderMenu')
        self.course_builder_action.triggered.connect(self._show_course_builder)
        file_menu.addSeparator()
        self.open_project_action = QAction("Open &Project…", self)
        self.open_project_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.open_project_action.triggered.connect(self._choose_project)
        self.save_project_action = QAction("&Save Project", self)
        self.save_project_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_project_action.triggered.connect(self._save_project)
        self.save_project_as_action = QAction("Save Project &As…", self)
        self.save_project_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_project_as_action.triggered.connect(lambda: self._save_project(save_as=True))
        self.save_rom_action = QAction("Save As Edited &ROM…", self)
        self.save_rom_action.setShortcut(QKeySequence("Ctrl+Alt+S"))
        self.save_rom_action.setStatusTip("Write a new .z64 with edited objects and level settings and validated N64 checksums")
        self.save_rom_action.triggered.connect(self._choose_save_rom)
        file_menu.addActions([self.open_project_action, self.save_project_action, self.save_project_as_action, self.save_rom_action])
        self.export_report_action = QAction("ROM &Budget and Project Changes…", self)
        self.export_report_action.triggered.connect(self._show_export_report)
        file_menu.addAction(self.export_report_action)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self._undo)
        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.redo_action.triggered.connect(self._redo)
        self.revert_object_action = QAction("Revert Selected Object", self)
        self.revert_object_action.triggered.connect(self._revert_selected)
        edit_menu.addActions([self.undo_action, self.redo_action, self.revert_object_action])
        edit_menu.addSeparator()
        self.add_object_action = QAction('Add Object...', self)
        self.add_object_action.triggered.connect(self._add_object)
        self.duplicate_objects_action = QAction('Duplicate Selected Objects', self)
        self.duplicate_objects_action.setShortcut(QKeySequence('Ctrl+D'))
        self.duplicate_objects_action.triggered.connect(self._duplicate_objects)
        self.delete_objects_action = QAction('Delete Selected Objects', self)
        self.delete_objects_action.setShortcut(QKeySequence('Ctrl+Delete'))
        self.delete_objects_action.triggered.connect(self._delete_objects)
        edit_menu.addActions([self.add_object_action, self.duplicate_objects_action, self.delete_objects_action])
        edit_menu.addSeparator()
        edit_menu.addActions([self.course_builder_action,self.course_names_action,self.image_browser_action,self.global_objects_action,self.model_editor_action])
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addActions([self.level_dock.toggleViewAction(), self.inspector_dock.toggleViewAction()])
        view_menu.addAction(self.camera_toolbar.toggleViewAction())
        view_menu.addAction(self.animation_toolbar.toggleViewAction())
        view_menu.addAction(self.animation_toolbar.models)
        view_menu.addAction(self.special_toolbar.toggleViewAction())
        view_menu.addAction(self.special_toolbar.visible)
        view_menu.addAction(self.environment_toolbar.toggleViewAction())
        view_menu.addSeparator()
        view_menu.addActions([self.toolbar.grid, self.toolbar.axes, self.toolbar.fit])
        view_menu.addSeparator()
        view_menu.addActions([self.toolbar.wireframe, self.toolbar.vertex_colors, self.toolbar.bounds,
                              self.toolbar.culling, self.toolbar.isolate, self.toolbar.textures,
                              self.toolbar.sprites,self.toolbar.objects,self.toolbar.racelines])
        help_menu = self.menuBar().addMenu("&Help")
        controls = help_menu.addAction("Camera &Controls")
        controls.triggered.connect(self._show_controls)
        graphics = help_menu.addAction("Graphics / &GPU…")
        graphics.triggered.connect(self._show_graphics)
        help_menu.addSeparator()
        about = help_menu.addAction("About")
        about.triggered.connect(self._show_about)
        

    @Slot()
    def _choose_rom(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Diddy Kong Racing USA Rev 1", str(self._last_directory),
            "N64 ROMs (*.z64 *.v64 *.n64);;All files (*)",
        )
        if path:
            self.load_rom(Path(path))

    def load_rom(self, path: Path, *, show_errors: bool = True) -> bool:
        return self._load_catalog(path, extracted=False, show_errors=show_errors)


    def _load_catalog(self, path: Path, *, extracted: bool, show_errors: bool, discard_confirmed: bool = False) -> bool:
        catalog: LevelCatalog | None = None
        failure: str | None = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            source = DecompAssets.from_directory(path) if extracted else RomImage.from_file(path)
            catalog = load_level_catalog(source)
            database = load_object_database(source)
            session = EditSession(source, database) if isinstance(source, RomImage) else None
        except (OSError, ValueError) as error:
            failure = str(error)
        finally:
            QApplication.restoreOverrideCursor()
        if failure is not None:
            if show_errors:
                QMessageBox.warning(self, "Cannot load level catalog", failure)
            return False
        assert catalog is not None
        if not discard_confirmed and not self._confirm_unsaved():
            return False
        source = catalog.source
        # Replace the current source only after its entire catalog validates.
        self.object_inspector.cinematics.clear_drafts()
        self.catalog = catalog
        if self.image_browser is not None:
            self.image_browser.close()
            self.image_browser.deleteLater()
            self.image_browser = None
        self.image_browser_action.setEnabled(True)
        self.object_database = database
        self.edit_session = session
        self.object_inspector.level_settings.session = session
        self.object_inspector.set_editing_enabled(session is not None)
        self._object_map_cache.clear()
        self._sprite_cache.clear()
        self._sprite_texture_cache.clear()
        self.object_library = None
        self.special_library = None
        self._preview_selection = None
        self.viewport.set_model_instances(None,())
        self._clear_sprites()
        self.current_objects = ()
        self.viewport.set_objects((),())
        self.object_inspector.set_objects(())
        self.toolbar.set_object_count(0)
        self.selected_level = None
        self.current_model = None
        self.current_textures = {}
        self._texture_cache.clear()
        self._model_cache.clear()
        self.viewport.set_model(None)
        self.toolbar.set_segment_count(0)
        self.export_action.setEnabled(False)
        self._update_material_panel()
        self._last_directory = path if extracted else path.parent
        self.level_panel.set_catalog(catalog)
        self.open_rom_action.setToolTip(source.description)
        self._update_edit_actions()
        self.statusBar().showMessage(f"Loaded {len(catalog.levels)} levels · {source.description}", 8000)
        return True

    @Slot(int)
    def _select_level(self, index: int) -> None:
        self._commit_editor()
        self.object_inspector.materials.cancel_preview()
        self.viewport.finish_object_drag(cancel=True)
        self.viewport.release_cinematic_camera()
        if self.catalog is None or not 0 <= index < len(self.catalog.levels):
            return
        self.selected_level = self.catalog.levels[index]
        if self.edit_session is not None:
            self.selected_level = replace(self.selected_level, header=self.edit_session.level_header(index))
        self.object_inspector.show_level(self.selected_level)
        model_id = self.selected_level.header.geometry_id
        try:
            if self.edit_session is not None:
                self.current_model = self.edit_session.track_model(model_id)
            else:
                if model_id not in self._model_cache:
                    self._model_cache[model_id] = load_level_model(self.catalog.source, model_id)
                self.current_model = self._model_cache[model_id]
            self.current_textures = load_model_textures(self.art_source, self.current_model, self._texture_cache)
        except (ValueError, OSError) as error:
            self._clear_sprites()
            self.current_model = None
            self.current_textures = {}
            self._update_material_panel()
            self.current_objects = ()
            self.viewport.set_objects((),())
            self.object_inspector.set_objects(())
            self.toolbar.set_object_count(0)
            self.viewport.set_model(None)
            self.toolbar.set_segment_count(0)
            self.export_action.setEnabled(False)
            self.object_inspector.hint.setText(f"Cannot load track geometry: {error}")
            self.viewport.set_catalog_caption(self.selected_level.name, model_id)
            QMessageBox.warning(self, "Cannot load track geometry", str(error))
            return
        self.viewport.set_model(self.current_model, self.current_textures)
        camera = self.viewport.camera
        if camera.view == "Perspective":
            camera.position = np.asarray(camera.target + (camera.position - camera.target) * np.float32(0.60), dtype=np.float32)
        self.viewport.update()
        self.toolbar.set_segment_count(len(self.current_model.segments))
        self.export_action.setEnabled(True)
        self.object_inspector.show_model(self.current_model)
        self.viewport.set_catalog_caption(self.selected_level.name, self.selected_level.header.geometry_id)
        self._load_level_objects()
        self._update_material_panel()
        if self.object_inspector.level_settings.preview_fov.isChecked():
            self._set_level_fov_preview(True)

    @Slot(bool)
    def _set_level_fov_preview(self, enabled: bool) -> None:
        if enabled and self.selected_level is not None:
            if self._saved_preview_fov is None:
                self._saved_preview_fov = self.viewport.camera.fov
            self.viewport.camera.fov = float(self.selected_level.header.camera_fov)
        elif self._saved_preview_fov is not None:
            self.viewport.camera.fov = self._saved_preview_fov
            self._saved_preview_fov = None
        self.viewport.update()

    @Slot(bool)
    def _sync_grid_controls(self, visible: bool) -> None:
        for action, value in ((self.toolbar.grid, visible),
                              (self.toolbar.grid_auto, self.viewport._grid_preference is None)):
            previous = action.blockSignals(True)
            action.setChecked(value)
            action.blockSignals(previous)

    @Slot(bool)
    def _sync_grid_follow(self, enabled: bool) -> None:
        previous = self.toolbar.grid_follow.blockSignals(True)
        self.toolbar.grid_follow.setChecked(enabled)
        self.toolbar.grid_follow.blockSignals(previous)

    def _refresh_level_settings(self, index: int) -> None:
        if self.catalog is None or self.edit_session is None:
            return
        if self.selected_level is None or self.selected_level.index != index:
            # A deferred edit belongs to its originating level, not the current
            # scene. Background completion must never navigate the level tree.
            self._update_edit_actions()
            if self.image_browser is not None:
                self.image_browser.refresh_context()
            return
        else:
            self.selected_level = replace(self.catalog.levels[index], header=self.edit_session.level_header(index))
            self.object_inspector.show_level(self.selected_level)
            if self.current_model is not None:
                self.object_inspector.show_model(self.current_model)
            self._update_routes()
            self._update_environment()
            if self.object_inspector.level_settings.preview_fov.isChecked():
                self._set_level_fov_preview(True)
        self._update_edit_actions()
        if self.image_browser is not None:
            self.image_browser.refresh_context()

    @Slot(int, str, object)
    def _apply_level_setting(self, index: int, key: str, value: object) -> None:
        self.viewport.finish_object_drag()
        session = self.edit_session
        if session is None:
            return
        try:
            changed = session.set_level_field(index, key, value)
            self._refresh_level_settings(index)
            if changed and self.selected_level is not None and self.selected_level.index == index:
                self.object_inspector.level_settings.message.setText("Setting applied. Ctrl+Z undoes the change.")
        except ValueError as error:
            self._refresh_level_settings(index)
            if self.selected_level is not None and self.selected_level.index == index:
                self.object_inspector.level_settings.message.setText(f"Edit rejected: {error}")
            else:
                self.statusBar().showMessage(f"Level {index} edit rejected: {error}", 8000)

    @Slot(int)
    def _revert_level_settings(self, index: int) -> None:
        self._commit_editor()
        if self.edit_session is not None:
            try:
                self.edit_session.revert_level(index)
                self._refresh_level_settings(index)
            except ValueError as error:
                self.object_inspector.level_settings.message.setText(f'Revert rejected: {error}')

    def _load_level_objects(self) -> None:
        if self.catalog is None or self.selected_level is None or self.object_database is None:
            return
        header = self.selected_level.header
        try:
            maps = tuple(dict.fromkeys(i for i in (header.object_map_id, header.secondary_object_map_id) if i >= 0))
            for map_id in maps:
                if self.edit_session is not None:
                    self._object_map_cache[map_id] = self.edit_session.current_map(map_id)
                elif map_id not in self._object_map_cache:
                    self._object_map_cache[map_id] = load_object_map(self.catalog.source,map_id,self.object_database)
            self.current_objects = tuple(obj for map_id in maps for obj in self._object_map_cache[map_id].objects)
            paths = build_race_paths(self.current_objects,header.checkpoint_sets,
                                    vehicle=int(self.toolbar.vehicle.currentData()),lane=int(self.toolbar.lane.currentData()))
        except (OSError,ValueError) as error:
            self._clear_sprites()
            self.current_objects = ()
            self.viewport.set_objects((),())
            self.object_inspector.set_objects(())
            self.toolbar.set_object_count(0)
            self.object_inspector.hint.setText(f"Geometry loaded; cannot load objects: {error}")
            self.statusBar().showMessage(f"Cannot load objects: {error}",10000)
            return
        self.viewport.set_objects(self.current_objects,paths)
        self.object_inspector.set_objects(self.current_objects)
        self.toolbar.set_object_count(len(self.current_objects))
        self.animation_toolbar.play.setChecked(False)
        self.viewport.set_preview_time(0.0)
        self.animation_toolbar.set_channels({int(obj.value('channel',0)) for obj in self.current_objects if obj.definition.behavior_id == 49})
        self._update_model_artwork()
        try:
            self.current_sprites = load_level_sprites(self.art_source, self.current_objects,
                                                      self._sprite_cache, self._sprite_texture_cache)
            self.current_sprites += self._animation_sprites()
        except (OSError, ValueError) as error:
            self._clear_sprites()
            self.statusBar().showMessage(f"Objects loaded; cannot load sprites: {error}", 10000)
            return
        self.viewport.set_sprites(self.current_sprites)
        self.toolbar.set_sprite_count(len(self.current_sprites))
        self._update_edit_actions()

    def _clear_sprites(self) -> None:
        self.current_sprites = ()
        self.viewport.set_sprites(())
        self.toolbar.set_sprite_count(0)
        self.viewport.set_model_instances(self.object_library,())
        self.viewport.set_special_instances(())
        self.special_toolbar.summary.setText('')
        self.viewport.set_environment(None, None, None, None, None, {})
        self._environment_key = None
        self._cinematic_key = None
        self.viewport.set_cinematics(())
        self.object_inspector.cinematics.set_tracks((), False)

    def _animation_sprites(self) -> tuple[SpriteInstance,...]:
        if self.catalog is None or self.object_database is None:
            return ()
        return animation_sprites(self.art_source,self.current_objects,self.object_database,
            int(self.animation_toolbar.channel.currentData() or 0),self._sprite_cache,self._sprite_texture_cache)

    def _update_model_artwork(self) -> None:
        if self.catalog is None or self.object_database is None:
            return
        try:
            if self.object_library is None:
                self.object_library = ObjectLibrary(self.art_source)
            instances = model_instances(self.current_objects,self.object_database,int(self.animation_toolbar.channel.currentData() or 0))
            for instance in instances:
                self.object_library.model(instance.model_id)
                self.object_library.clip(instance.model_id,instance.clip_index)
            self.viewport.set_model_instances(self.object_library,instances)
            self.animation_toolbar.summary.setText(f' {len(instances)} models · clip preview')
            self.animation_toolbar.models.setEnabled(bool(instances))
        except (ValueError,OSError) as error:
            self.viewport.set_model_instances(self.object_library,())
            self.animation_toolbar.summary.setText(' Artwork unavailable')
            self.animation_toolbar.summary.setToolTip(str(error))
            self.statusBar().showMessage(f'Cannot load object artwork: {error}',10000)
        self._preview_selection_changed(self.viewport.selected_object)
        self._update_special_artwork()
        self._update_environment()
        self._update_cinematics()

    def _update_cinematics(self) -> None:
        if self.object_database is None:
            return
        channel = int(self.animation_toolbar.channel.currentData() or 0)
        # Tracks own flattened viewport indices, whereas o.key is a stable editor
        # identity. Inserting/deleting another object can shift a track without
        # changing any of its nodes; refresh before a stale owner poses scenery.
        key = (tuple((index, o.key, o.position, o.parameters) for index, o in enumerate(self.current_objects)
                     if o.definition.behavior_id == 49),
               channel, id(self.object_library))
        if key == self._cinematic_key:
            return
        tracks = build_tracks(self.current_objects, self.object_database, channel)
        timelines: list[CinematicTimeline] = []
        for track in tracks:
            lengths: dict[int, int] = {}
            if self.object_library is not None and track.target is not None and track.target.model_type == 0 and track.target.model_ids and not track.camera:
                for clip_id in {int(node.value('objAnimIndex', -1)) for node in track.nodes}:
                    clip = self.object_library.clip(track.target.model_ids[0], clip_id)
                    if clip is not None:
                        lengths[clip_id] = clip.frame_count
            timelines.append(CinematicTimeline(track, lengths))
        camera_owner = self.viewport.cinematic_camera
        self._cinematic_key = key
        self.viewport.set_cinematics(tuple(timelines))
        self.object_inspector.cinematics.set_tracks(tuple(timelines), self.edit_session is not None)
        if camera_owner >= 0 and any(track.owner == camera_owner and track.camera for track in tracks):
            self.object_inspector.cinematics.camera.setChecked(True)

    def _cinematic_duration(self, seconds: float) -> None:
        self.viewport.preview_duration = seconds
        self.animation_toolbar.time.setMaximum(round(seconds*60))
        self.viewport.set_preview_time(min(self.viewport.preview_time, seconds))

    def _cinematic_parameter(self, key: ObjectKey, field: str, value: object) -> None:
        self._commit_editor()
        if self.edit_session is not None:
            try:
                self.edit_session.set_parameter(key, field, value)
                self._refresh_edits(key)
            except ValueError as error:
                self.object_inspector.cinematics.feedback.setText(str(error))

    def _update_environment(self) -> None:
        if self.selected_level is None or self.current_model is None or self.object_library is None:
            return
        header = self.selected_level.header
        rates = scroll_rates(self.current_objects, len(self.current_model.textures))
        key = (id(self.current_model), id(self.current_textures), header, id(self.object_library), tuple(sorted(rates.items())))
        if key == self._environment_key:
            return
        try:
            sky = self.object_database.definitions[header.skybox_id] if self.object_database is not None and header.skybox_id >= 0 and header.special_sky != -1 else None
            if sky is not None and sky.model_ids:
                self.object_library.model(sky.model_ids[0])
            water = water_preview(self.current_model, WaveSettings.from_header(header), self.current_textures)
            if water is not None and water.settings.translucent:
                ident = water.settings.texture_id
                detail = load_texture(self.art_source, ident & 0x7FFF,
                    asset_type=AssetType.TEXTURES_3D if ident & 0x8000 else AssetType.TEXTURES_2D)
                water = replace(water, detail=detail)
            flash = None
            if header.special_sky == -1:
                section = AssetType.TEXTURES_3D if header.special_sky_texture & 0x8000 else AssetType.TEXTURES_2D
                flash = load_texture(self.art_source, header.special_sky_texture & 0x7FFF, asset_type=section)
            self.viewport.set_environment(header, self.object_library, sky, water, flash, rates)
            self._environment_key = key
            note = 'Flash sky: texture plane; color scripts omitted' if flash else 'Preview only · Play/scrub controls motion'
            self.environment_toolbar.set_summary(note)
        except (ValueError, OSError) as error:
            self.viewport.set_environment(header, None, None, None, None, rates)
            self.environment_toolbar.set_summary('Some environment graphics unavailable')
            self.statusBar().showMessage(f'Cannot load environment: {error}', 10000)

    def _update_special_artwork(self) -> None:
        if self.art_source is None:
            return
        try:
            if self.special_library is None or self.special_library.source is not self.art_source:
                self.special_library = SpecialLibrary(self.art_source)
            instances = self.special_library.instances(self.current_objects, self.current_model,
                int(self.special_toolbar.portrait.currentData()))
            self.viewport.set_special_instances(instances)
            counts = {kind: sum(item.kind == kind for item in instances) for kind in ('zipper', 'fish', 'butterfly', 'portrait')}
            names = {'zipper': 'zippers', 'fish': 'fish', 'butterfly': 'butterflies', 'portrait': 'portraits'}
            labels = [f'{count} {kind if count == 1 else names[kind]}' for kind, count in counts.items() if count]
            if any(obj.definition.behavior_id == 89 for obj in self.current_objects):
                labels.append('boost needs racers')
            self.special_toolbar.summary.setText('  ' + ' · '.join([*labels, 'preview only']) if labels else '')
            self.special_toolbar.visible.setEnabled(bool(instances))
        except (ValueError, OSError) as error:
            self.viewport.set_special_instances(())
            self.special_toolbar.summary.setText(' Special artwork unavailable')
            self.statusBar().showMessage(f'Cannot load special artwork: {error}', 10000)

    @Slot(int)
    def _preview_channel_changed(self, index: int) -> None:
        self.viewport.finish_object_drag(cancel=True)
        self.viewport.set_preview_time(0.0)
        self._update_model_artwork()
        if self.catalog is not None:
            try:
                self.current_sprites = load_level_sprites(self.art_source,self.current_objects,self._sprite_cache,self._sprite_texture_cache)+self._animation_sprites()
                self.viewport.set_sprites(self.current_sprites)
                self.toolbar.set_sprite_count(len(self.current_sprites))
            except (ValueError,OSError) as error:
                self.statusBar().showMessage(f'Cannot load scene sprites: {error}',10000)

    @Slot(int)
    def _preview_selection_changed(self, index: int) -> None:
        instance = next((item for item in self.viewport.model_instances if item.object_index == index),None)
        selection = (index,instance.model_id) if instance is not None else None
        if selection == self._preview_selection and self.animation_toolbar.clip.count() > 0:
            return
        self._preview_selection = selection
        count = self.object_library.clip_count(instance.model_id) if instance is not None and self.object_library is not None else 0
        self.animation_toolbar.set_clips(count)
        self.viewport.preview_clip = -1

    @Slot(int)
    def _preview_clip_changed(self, row: int) -> None:
        value = int(self.animation_toolbar.clip.currentData() or 0)
        instance = next((item for item in self.viewport.model_instances if item.object_index == self.viewport.selected_object),None)
        if instance is not None and self.object_library is not None:
            try:
                self.object_library.clip(instance.model_id,value if value >= 0 else instance.clip_index)
            except (ValueError,OSError) as error:
                self.statusBar().showMessage(str(error),10000)
                return
        self.viewport.preview_clip = value
        self.viewport.update()

    @Slot()
    def _update_routes(self) -> None:
        if self.selected_level is not None:
            self.viewport.set_paths(build_race_paths(self.current_objects,self.selected_level.header.checkpoint_sets,
                                    vehicle=int(self.toolbar.vehicle.currentData()),lane=int(self.toolbar.lane.currentData())))

    @Slot(int)
    def _focus_object(self, index: int) -> None:
        self.toolbar.objects.setChecked(True)
        self.viewport.focus_object(index)
        self._update_edit_actions()

    @Slot(int)
    def _select_picked_object(self, index: int) -> None:
        indices = self.viewport.selected_objects
        if 0 <= index < len(self.current_objects) and self.object_inspector.object_list.topLevelItem(index).isHidden():
            self.object_inspector.object_search.clear()
            self.object_inspector.category.setCurrentIndex(0)
        self.object_inspector.set_selection(indices, index, reveal=True)
        self._update_placement()

    @Slot(object, int)
    def _select_group(self, indices: tuple[int, ...], primary: int) -> None:
        self.viewport.set_selection(indices, primary)
        self._update_placement()

    def _selected_entries(self) -> tuple[LevelObject, ...]:
        primary = self.viewport.selected_object
        indices = ((primary,) + tuple(i for i in self.viewport.selected_objects if i != primary)) if primary >= 0 else ()
        return tuple(self.current_objects[i] for i in indices if 0 <= i < len(self.current_objects))

    def _update_placement(self) -> None:
        objects = self._selected_entries()
        if hasattr(self, 'duplicate_objects_action'):
            self.duplicate_objects_action.setEnabled(self.edit_session is not None and bool(objects))
            self.delete_objects_action.setEnabled(self.edit_session is not None and bool(objects))
        enabled = self.edit_session is not None
        self.object_inspector.placement.set_selection(objects, enabled)
        primary = objects[0] if objects else None
        sets = self.selected_level.header.checkpoint_sets if self.selected_level else (0, 0, 0)
        self.object_inspector.routes.show_context(self.current_objects, primary if primary and primary.definition.behavior_id in (13, 16) else None, sets, enabled)
        self.object_inspector.research.show_context(self.edit_session, primary)
        self.object_inspector.minimap.set_objects(self.current_objects, primary)
        if primary is not None and primary.definition.behavior_id == 49:
            self.object_inspector.cinematics.select_node(primary.key)
        self._route_preview()
        if self._connection_source is not None and (primary is None or primary.key != self._connection_source):
            self._connection_source = None
            self.viewport.route_pick_slot = None
        self.viewport.rotation_axes = rotation_axes(objects)
        self.viewport.scale_supported = can_scale(objects)
        for row, supported in ((1, bool(self.viewport.rotation_axes)), (2, self.viewport.scale_supported)):
            self.camera_toolbar.transform.model().item(row).setEnabled(enabled and supported)
        self.camera_toolbar.transform.setEnabled(enabled and bool(objects))
        if ((self.viewport.transform_mode == "Rotate" and not self.viewport.rotation_axes)
                or (self.viewport.transform_mode == "Scale" and not self.viewport.scale_supported)):
            self.camera_toolbar.transform.setCurrentIndex(0)

    def _route_preview(self) -> None:
        panel = self.object_inspector.routes
        active = (self.edit_session is not None and panel.obj is not None and panel.obj.definition.behavior_id == 13
                  and panel.drag.isChecked() and self.object_inspector.tools.currentWidget() is panel
                  and self.object_inspector.tabs.currentWidget() is self.object_inspector.tools)
        lane = panel.lane.currentIndex() if active else -1
        if self.viewport.route_lane != lane and self.viewport._drag is not None:
            self.viewport.finish_object_drag(cancel=True)
        self.viewport.route_lane = lane
        if active:
            self.toolbar.racelines.setChecked(True)
            self.toolbar.lane.setCurrentIndex(self.toolbar.lane.findData(4))
        self.viewport.update()

    def _select_route(self, key: ObjectKey, focus: bool = False) -> None:
        self._commit_editor()
        index = next((i for i, obj in enumerate(self.current_objects) if obj.key == key), -1)
        if index < 0:
            return
        self.object_inspector.object_search.clear()
        self.object_inspector.category.setCurrentIndex(0)
        self.viewport.set_selection((index,), index)
        self.object_inspector.set_selection((index,), index)
        self._update_edit_actions()
        if focus:
            self._focus_object(index)

    def _route_parameter(self, key: ObjectKey, field: str, value: object) -> None:
        self._commit_editor()
        if self.edit_session is not None:
            try:
                self.edit_session.set_parameter(key, field, value)
                self._refresh_edits(key)
            except ValueError as error:
                self.object_inspector.routes.message.setText(str(error))

    def _route_connection(self, key: ObjectKey, slot: int, target: int) -> None:
        self._commit_editor()
        if self.edit_session is None:
            return
        try:
            obj = self.edit_session.object(key)
            raw = connection_entry(obj, slot, target, self.current_objects)
            self.edit_session.apply_entries({key: raw}, f"Change AI connection slot {slot}")
            self._refresh_edits(key)
            self.toolbar.racelines.setChecked(True)
            self.object_inspector.routes.message.setText(f"Slot {slot} now targets {target}. Directed link changed; reciprocal slots are separate. Ctrl+Z undo.")
        except ValueError as error:
            self.object_inspector.routes.message.setText(f"Connection rejected: {error}")

    def _pick_connection(self, slot: int) -> None:
        self._commit_editor()
        selected = self._selected_entries()
        if selected and selected[0].definition.behavior_id == 16 and self.edit_session:
            self._connection_source = selected[0].key
            self.viewport.route_pick_slot = slot
            self.toolbar.objects.setChecked(True)
            self.toolbar.racelines.setChecked(True)
            self.object_inspector.routes.message.setText(f"Click an existing AI node in the viewport for slot {slot}. Escape cancels. No reciprocal connection is added.")

    def _connection_picked(self, index: int) -> None:
        slot = self.viewport.route_pick_slot
        key = self._connection_source
        if key is None or slot is None:
            return
        if not 0 <= index < len(self.current_objects) or self.current_objects[index].definition.behavior_id != 16:
            self.object_inspector.routes.message.setText("Choose an existing AI node marker; Escape cancels.")
            return
        self.viewport.route_pick_slot = None
        self._connection_source = None
        self._route_connection(key, slot, self.current_objects[index].value("nodeID"))

    def _research_note(self, key: ObjectKey, field: str, text: str, result: str) -> None:
        if self.edit_session:
            try:
                self.edit_session.set_note(key, field, text, result)
                self._update_edit_actions()
            except ValueError as error:
                self.object_inspector.research.message.setText(str(error))

    def _experiment_name(self, name: str) -> None:
        if self.edit_session:
            self.edit_session.set_experiment_name(name)
            self._update_edit_actions()

    def _compare_experiment(self) -> None:
        self._commit_editor()
        if self.edit_session is None:
            return
        chosen, _ = QFileDialog.getOpenFileName(self, "Compare project notes", str(self._last_directory), "DKR Projects (*.dkrproj)")
        if not chosen:
            return
        try:
            saved = EditSession.load_project(Path(chosen), base_path=self.edit_session.rom.source_path)
            rows = compare_sessions(self.edit_session, saved)
            ComparisonDialog(rows, saved.experiment_name or Path(chosen).name, self).exec()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Cannot compare project notes", str(error))

    def _update_material_panel(self) -> None:
        model = self.current_model
        session = self.edit_session
        levels = tuple(f"{level.index}: {level.name}" for level in self.catalog.levels
                       if model is not None and level.header.geometry_id == model.model_id) if self.catalog else ()
        original = session.track_base(model.model_id) if model is not None and session is not None else None
        changed = original is not None and copy_geometry(copy_minimap(model.raw_data, original), original) != original
        source = self.art_source
        def texture_for_material(texture_id: int) -> Texture:
            if texture_id not in self._texture_cache:
                self._texture_cache[texture_id] = load_texture(source, texture_id)
            return self._texture_cache[texture_id]
        material_original = copy_geometry(copy_minimap(original, model.raw_data), model.raw_data) if original is not None else None
        self.object_inspector.materials.show_context(model, self.current_textures, session.material_references if session else (),
            levels, session is not None, changed=changed, original=material_original,
            loader=texture_for_material if source is not None else None,
            flip=(lambda texture_id: png_flip_default(source, AssetType.TEXTURES_3D, texture_id)) if source is not None else None)
        try:
            refs = session.minimap_references if session and model is not None else sprite_references(self.catalog.source) if self.catalog and model is not None else ()
            self.object_inspector.minimap.show_context(model, self.art_source, refs, levels, session is not None,
                changed=original is not None and copy_minimap(original, model.raw_data) != original)
        except (ValueError, OSError) as error:
            self.object_inspector.minimap.show_context(None, None, (), (), False)
            self.object_inspector.minimap.message.setText(f"Cannot preview minimap: {error}")
        try:
            profile = geometry_profile(original) if original is not None else None
            self.object_inspector.geometry_panel.show_context(model, profile, levels, session is not None,
                original is not None and geometry_changed(original, model.raw_data))
        except ValueError as error:
            self.object_inspector.geometry_panel.show_context(model, None, levels, False, False)
            self.object_inspector.geometry_panel.message.setText(f'Geometry unavailable: {error}')
        self.object_inspector.geometry_panel.stock.setEnabled(model is not None and session is not None and session.imported_track(model.model_id))
        imported = model is not None and session is not None and session.imported_track(model.model_id)
        self.object_inspector.minimap.revert.setText('Revert minimap to import baseline' if imported else 'Revert minimap to original ROM')
        if imported:
            self.object_inspector.geometry_panel.summary.setText(f'Model {model.model_id} · imported static track\nShared levels: '+(', '.join(levels) or 'none'))
        self.object_inspector.geometry_panel.revert.setToolTip('Restore coordinates from the imported model; keep materials and minimap edits.' if imported else 'Restore original ROM coordinates; keep materials and minimap edits.')
        self._material_preview()

    @property
    def art_source(self) -> RomImage | DecompAssets | None:
        return self.edit_session.asset_source if self.edit_session else self.catalog.source if self.catalog else None

    def _open_image_browser(self, section: AssetType = AssetType.TEXTURES_3D, index: int | None = None) -> None:
        self._commit_editor()
        if self.art_source is None or self.object_database is None:
            return
        if self.image_browser is None:
            self.image_browser = ImageBrowser(self.art_source, self.edit_session, self.object_database, self)
            self.image_browser.assets_changed.connect(self._refresh_graphics)
            self.image_browser.history_requested.connect(lambda redo: self._redo() if redo else self._undo())
        if index is not None:
            self.image_browser.select_asset(section, index)
        self.image_browser.show()
        self.image_browser.raise_()
        self.image_browser.activateWindow()

    def _reset_image_cache(self) -> None:
        self._texture_cache.clear()
        self._sprite_cache.clear()
        self._sprite_texture_cache.clear()
        self.special_library = None
        self._environment_key = None
        self.object_inspector.minimap._art_cache.clear()
        if self.object_library is not None:
            self.object_library.source = self.art_source
            self.object_library.textures.clear()
            self.object_library.models.clear()
            self.object_library.clips.clear()

    def _refresh_graphics(self) -> None:
        self._reset_image_cache()
        if self.current_model is not None and self.art_source is not None:
            self.current_textures = load_model_textures(self.art_source, self.current_model, self._texture_cache)
            self.viewport.refresh_materials(self.current_model, self.current_textures)
            self.current_sprites = load_level_sprites(self.art_source, self.current_objects, self._sprite_cache, self._sprite_texture_cache) + self._animation_sprites()
            self.viewport.set_sprites(self.current_sprites)
            self._update_model_artwork()
            self.viewport._object_mesh_dirty = True
            self.toolbar.set_sprite_count(len(self.current_sprites))
        self._update_material_panel()
        self._update_edit_actions()
        if self.image_browser is not None and self.sender() is not self.image_browser:
            self.image_browser.refresh()

    def _edit_minimap(self, changes: dict[str, int | float]) -> None:
        self._commit_editor()
        if self.edit_session is None or self.current_model is None:
            return
        index = self.current_model.model_id
        try:
            self.edit_session.edit_minimap(index, changes)
            self._refresh_track_model(index)
            self.object_inspector.minimap.message.setText("Settings applied. Ctrl+Z undoes the change.")
        except (ValueError, OSError) as error:
            self.object_inspector.minimap.message.setText(f"Minimap edit rejected: {error}")

    def _revert_minimap(self) -> None:
        self._commit_editor()
        if self.edit_session is not None and self.current_model is not None:
            index = self.current_model.model_id
            self.edit_session.revert_minimap(index)
            self._refresh_track_model(index)

    def _material_preview(self) -> None:
        panel = self.object_inspector.materials
        geometry = self.object_inspector.geometry_panel
        geometry_active = (self.object_inspector.tabs.currentWidget() is self.object_inspector.geometry_tabs
            and self.object_inspector.geometry_tabs.currentWidget() is geometry
            and self.current_model is not None)
        self.viewport.material_isolation = None
        if not geometry_active and self.viewport._drag_is_geometry:
            self.viewport.finish_object_drag(cancel=True)
        self.viewport.geometry_active = geometry_active
        self.viewport.geometry_picking = geometry_active and geometry.pick.isChecked() and geometry.enabled
        self.viewport.geometry_faces = geometry.mode.currentIndex() == 1
        self.viewport.geometry_segment = int(geometry.segment.currentData()) if geometry.segment.currentData() is not None else -1
        self.viewport.geometry_step = geometry.step.value()
        self.viewport.geometry_center = None
        if geometry_active:
            panel.cancel_preview()
            keys = geometry.selected_vertices()
            linked = linked_vertices(geometry.profile, keys) if geometry.profile else keys
            self.viewport.material_vertices = linked
            self.viewport.material_faces = geometry.selected_faces()
            if keys:
                self.viewport.geometry_center = np.array(selection_center(self.current_model, keys), np.float32)
            self.viewport.material_active = True
            self.viewport.material_picking = False
            self.viewport.update()
            return
        active = (self.object_inspector.geometry_tabs.currentWidget() is panel
                  and self.object_inspector.tabs.currentWidget() is self.object_inspector.geometry_tabs
                  and panel.model is self.current_model and self.current_model is not None)
        self.viewport.material_active = active
        self.viewport.material_picking = active and panel.pick.isChecked()
        faces: tuple[tuple[int, int], ...] = ()
        vertices: tuple[tuple[int, int], ...] = ()
        if active:
            faces, vertices = panel.highlighted_faces(), panel.highlighted_vertices()
            self.viewport.material_isolation = panel.isolated_batch
        else:
            panel.cancel_preview()
        self.viewport.material_faces, self.viewport.material_vertices = faces, vertices
        self.viewport.update()

    def _show_face_material(self, segment: int, face: int) -> None:
        self._commit_editor()
        self.object_inspector.tabs.setCurrentWidget(self.object_inspector.geometry_tabs)
        panel = self.object_inspector.materials
        self.object_inspector.geometry_tabs.setCurrentWidget(panel)
        panel.pick.setChecked(True)
        panel.pick_face(segment, face)

    @Slot(object)
    def _preview_materials(self, preview: object) -> None:
        if self.current_model is None:
            return
        if preview is None:
            self.viewport.refresh_materials(self.current_model, self.current_textures)
        else:
            model, textures = preview
            if model.model_id != self.current_model.model_id:
                return
            self.viewport.refresh_materials(model, dict(textures))
        self._material_preview()

    def _show_stock_rebuild(self) -> None:
        self._commit_editor()
        if self.edit_session is None or self.current_model is None:
            return
        name = self.selected_level.name if self.selected_level is not None else 'Selected track'
        dialog = TrackRebuildDialog(self.edit_session.rom, self.current_model.model_id, name, self)
        dialog.exec()

    def _show_track_import(self) -> None:
        if self.edit_session is None or self.current_model is None:
            return
        session = self.edit_session
        index = self.current_model.model_id
        self._commit_editor()
        if self.edit_session is not session or self.current_model is None or self.current_model.model_id != index:
            self.statusBar().showMessage('Import target changed; select the intended course and open Import again.', 8000)
            return
        dialog = TrackImportDialog(session, index, self.current_objects, self, paths=self.viewport.paths)
        if dialog.exec():
            self._refresh_track_model(index)
            self.object_inspector.geometry_panel.message.setText('Track imported. Align the objects, start grid and checkpoints with the new course before exporting.')
        dialog.deleteLater()

    def _show_course_builder(self) -> None:
        self._commit_editor()
        if self.edit_session is None or self.selected_level is None or self.current_model is None:return
        dialog=CourseBuilder(self.edit_session,self.selected_level.index,self)
        if dialog.exec():
            keys=dialog.plan.selection if dialog.plan else ()
            self._refresh_edits(keys[0] if keys else None)
            self._select_object_keys(keys)
            self.object_inspector.routes.message.setText('Course applied. Save the project or export your ROM.')
        dialog.deleteLater()

    def _show_course_names(self) -> None:
        self._commit_editor()
        if self.edit_session is None:return
        dialog=CourseNamesDialog(self.edit_session,self.selected_level.index if self.selected_level else 0,self)
        dialog.names_changed.connect(self._refresh_course_names)
        dialog.history_requested.connect(lambda redo:self._redo() if redo else self._undo())
        dialog.exec();dialog.deleteLater()

    def _show_global_objects(self) -> None:
        self._commit_editor()
        if self.edit_session is None:
            return
        selected = self._selected_entries()
        index = selected[0].definition.header_id if selected else 0
        dialog = GlobalObjectsDialog(self.edit_session, index, self)
        dialog.definitions_changed.connect(self._refresh_global_objects)
        dialog.history_requested.connect(lambda redo: self._redo() if redo else self._undo())
        dialog.exec()
        dialog.deleteLater()

    def _show_model_editor(self) -> None:
        self._commit_editor()
        if self.edit_session is None:
            return
        selected = self._selected_entries()
        index = 0
        if selected:
            instance = next((i for i in self.viewport.model_instances if self.current_objects[i.object_index].key == selected[0].key), None)
            if instance is not None:
                index = instance.model_id
            elif selected[0].definition.model_type == 0 and selected[0].definition.model_ids:
                index = selected[0].definition.model_ids[0]
        dialog = ModelEditorDialog(self.edit_session, index, self)
        dialog.assets_changed.connect(self._refresh_model_assets)
        dialog.history_requested.connect(lambda redo: self._redo() if redo else self._undo())
        dialog.exec()
        dialog.viewport.cleanup()
        dialog.deleteLater()

    def _refresh_model_assets(self) -> None:
        self._cinematic_key = None
        self.object_library = None
        self._refresh_global_objects()

    def _refresh_global_objects(self) -> None:
        if self.edit_session is None:
            return
        self.object_database = self.edit_session.database
        self._object_map_cache.clear()
        self._cinematic_key = None
        self._reset_image_cache()
        self.current_sprites = ()  # New decoded image owners must not be compared through NumPy equality.
        selected = self._selected_entries()
        self._refresh_edits(selected[0].key if selected else None)
        self.viewport._object_mesh_dirty = True
        if self.image_browser is not None:
            self.image_browser.database = self.object_database
            self.image_browser.refresh()
        self._update_edit_actions()

    def _refresh_course_names(self) -> None:
        if self.catalog is None or self.edit_session is None:return
        self.catalog=replace(self.catalog,levels=self.edit_session._catalog.levels)
        self.level_panel.refresh_names(self.catalog)
        if self.selected_level is not None:
            self.selected_level=replace(self.selected_level,names=self.edit_session.course_names(self.selected_level.index))
            self.object_inspector.show_level(self.selected_level)
            if self.current_model is not None:self.object_inspector.show_model(self.current_model)
            self.viewport.set_catalog_caption(self.selected_level.name,self.selected_level.header.geometry_id)
        self._update_edit_actions()
        if self.image_browser is not None:
            self.image_browser.refresh()

    def _restore_stock_track(self) -> None:
        self._commit_editor()
        if self.edit_session is not None and self.current_model is not None:
            index = self.current_model.model_id
            self.edit_session.restore_stock_track(index)
            self._refresh_track_model(index)
            self.object_inspector.geometry_panel.message.setText('Original ROM track restored as one undo step.')

    def _focus_batch(self, segment: int, batch: int) -> None:
        self._commit_editor()
        if self.current_model is None:
            return
        s = self.current_model.segments[segment]
        b, end = (s.batches + (s.terminal_batch,))[batch:batch + 2]
        points = s.vertices[s.indices[b.faces_offset:end.faces_offset]].reshape(-1, 3)
        if len(points):
            self.viewport.camera.fit_bounds(points.min(axis=0), points.max(axis=0), self.viewport.width() / max(self.viewport.height(), 1))
            self.viewport.update()

    def _refresh_track_model(self, index: int, *, reveal: bool = True) -> None:
        if self.edit_session is None or self.catalog is None:
            return
        if self.current_model is None or self.current_model.model_id != index:
            if not reveal:
                self._update_edit_actions()
                return
            level = next((level for level in self.catalog.levels if level.header.geometry_id == index), None)
            if level:
                self.level_panel.select_level(level.index)
            return
        previous = self.current_model
        # Undo can remove appended IDs, and a new import can reuse those IDs
        # for different artwork. Never retain a stale GPU/decoded texture owner.
        self._texture_cache.clear()
        if self.image_browser is not None:self.image_browser.refresh()
        self.current_model = self.edit_session.track_model(index)
        topology = (len(previous.raw_data) != len(self.current_model.raw_data)
            or previous.raw_data[:0x20] != self.current_model.raw_data[:0x20]
            or len(previous.segments) != len(self.current_model.segments)
            or any(a.vertex_count != b.vertex_count or not np.array_equal(a.indices, b.indices)
                   for a,b in zip(previous.segments,self.current_model.segments)))
        before_material = None if topology else copy_geometry(copy_minimap(previous.raw_data, self.current_model.raw_data), self.current_model.raw_data)
        if topology:
            # Old segment/vertex identities do not belong to a replacement mesh.
            tree = self.object_inspector.geometry_panel.tree
            tree.blockSignals(True)
            tree.clear()
            tree.blockSignals(False)
            self.current_textures = load_model_textures(self.art_source, self.current_model, self._texture_cache)
            self.viewport.set_model(self.current_model, self.current_textures)
            self.toolbar.set_segment_count(len(self.current_model.segments))
        elif before_material != self.current_model.raw_data:
            self.current_textures = load_model_textures(self.art_source, self.current_model, self._texture_cache)
            self.viewport.refresh_materials(self.current_model, self.current_textures)
        elif geometry_changed(previous.raw_data, self.current_model.raw_data):
            self.viewport.refresh_geometry(self.current_model)
        else:
            self.viewport.model = self.current_model
        self._terrain_cache = None
        self._update_special_artwork()
        self._update_environment()
        if self.selected_level is not None:
            self.viewport.set_catalog_caption(self.selected_level.name, index)
            if topology:
                self.object_inspector.show_level(self.selected_level)
        self.object_inspector.show_model(self.current_model, selected_segment=self.viewport.selected_segment)
        self._update_material_panel()
        self._update_edit_actions()

    def _edit_geometry(self, index: int, keys: tuple[VertexKey, ...], delta: Position) -> None:
        self._commit_editor()
        if self.edit_session is None:
            return
        try:
            changed = self.edit_session.edit_track_geometry(index, keys, delta)
            self._refresh_track_model(index, reveal=False)
            self.object_inspector.geometry_panel.message.setText('Geometry applied. Ctrl+Z undoes the change.' if changed else 'No coordinates changed.')
        except (ValueError, OSError) as error:
            self._update_material_panel()
            self.object_inspector.geometry_panel.message.setText(f'Geometry edit rejected: {error}')

    def _revert_geometry(self) -> None:
        self._commit_editor()
        if self.edit_session is not None and self.current_model is not None:
            index = self.current_model.model_id
            self.edit_session.revert_track_geometry(index)
            self._refresh_track_model(index)

    def _focus_geometry(self) -> None:
        self._commit_editor()
        keys = self.object_inspector.geometry_panel.selected_vertices()
        if self.current_model is not None and keys:
            points = np.array([self.current_model.segments[s].vertices[v] for s, v in keys])
            self.viewport.camera.fit_bounds(points.min(axis=0)-50, points.max(axis=0)+50,
                self.viewport.width()/max(self.viewport.height(), 1))
            self.viewport.update()

    def _geometry_drag_start(self) -> None:
        panel = self.object_inspector.geometry_panel
        keys = panel.selected_vertices()
        if self.edit_session is None or self.current_model is None or not keys:
            self.viewport.finish_object_drag(cancel=True)
            return
        index = self.current_model.model_id
        self._geometry_gesture = (index, self.edit_session.current_asset(AssetType.LEVEL_MODELS, index),
                                  keys, selection_center(self.current_model, keys))
        self._geometry_preview_raw = self._geometry_gesture[1]

    def _geometry_drag_preview(self, position: Position) -> None:
        if self._geometry_gesture is None or self.edit_session is None:
            return
        index, before, keys, center = self._geometry_gesture
        try:
            raw = move_vertices(self.edit_session.track_base(index), before,
                keys, tuple(int(a)-b for a, b in zip(position, center)))
            self._geometry_preview_raw = raw
            self.current_model = LevelModel.from_bytes(raw, model_id=index)
            self.viewport.refresh_geometry(self.current_model)
            self.object_inspector.geometry_panel.preview(self.current_model)
            self.object_inspector.geometry_panel.message.setText('Geometry preview. Release to apply; Esc cancels.')
        except ValueError as error:
            self.object_inspector.geometry_panel.message.setText(f'Move limited to last valid position: {error}')

    def _geometry_drag_finish(self, cancel: bool) -> None:
        gesture, raw = self._geometry_gesture, self._geometry_preview_raw
        self._geometry_gesture = self._geometry_preview_raw = None
        if gesture is None or self.edit_session is None:
            return
        index, _, _, _ = gesture
        try:
            if not cancel and raw is not None:
                self.edit_session.apply_track_geometry_preview(index, raw)
            self._refresh_track_model(index)
            self.object_inspector.geometry_panel.message.setText('Geometry move cancelled.' if cancel else 'Geometry applied. Ctrl+Z undoes the change.')
        except ValueError as error:
            self._refresh_track_model(index)
            self.object_inspector.geometry_panel.message.setText(f'Geometry edit rejected: {error}')

    def _edit_materials(self, index: int, edits: tuple[MaterialEdit, ...], label: str) -> None:
        self._commit_editor()
        if self.edit_session is None:
            return
        try:
            changed = self.edit_session.edit_track_materials(index, edits, label)
            self._refresh_track_model(index, reveal=False)
            self.object_inspector.materials.message.setText("Edit applied. Ctrl+Z undoes the change." if changed else "No stored values changed.")
        except (ValueError, OSError) as error:
            self._update_material_panel()
            self.object_inspector.materials.message.setText(f"Material edit rejected: {error}")

    def _revert_materials(self) -> None:
        self._commit_editor()
        if self.edit_session is not None and self.current_model is not None:
            index = self.current_model.model_id
            self.edit_session.revert_track_materials(index)
            self._refresh_track_model(index)

    def _refresh_asset(self) -> None:
        if self.edit_session is not None and self.edit_session.last_asset_key is not None:
            section, index = self.edit_session.last_asset_key
            if section == AssetType.LEVEL_MODELS:
                self._refresh_track_model(index)
            elif section==AssetType.LEVEL_NAMES:
                self._refresh_course_names()
            elif section == AssetType.OBJECTS:
                self._refresh_global_objects()
            elif section in (AssetType.OBJECT_MODELS, AssetType.OBJECT_ANIMATIONS):
                self._refresh_model_assets()
            elif section in IMAGE_SECTIONS:
                self._refresh_graphics()
            else:
                self._refresh_level_settings(index)

    def _terrain(self) -> TerrainSurface:
        if self.current_model is None:
            raise EditError("Load track geometry for surface placement")
        segment = self.viewport.selected_segment if self.viewport.isolate_segment else -1
        if self._terrain_cache is None or self._terrain_cache[0] is not self.current_model or self._terrain_cache[1] != segment:
            self._terrain_cache = self.current_model, segment, TerrainSurface.from_model(self.current_model, segment)
        return self._terrain_cache[2]

    def _surface_entries(self, entries: dict[ObjectKey, bytes], *, drop: bool) -> dict[ObjectKey, bytes]:
        import struct
        surface = self._terrain()
        offset = self.object_inspector.placement.offset.value()
        result = {}
        assert self.edit_session is not None
        for key, raw in entries.items():
            position = struct.unpack_from(">3h", raw, 2)
            height = surface.surface_y(position, drop=drop, offset=offset)
            if height is None:
                raise EditError(f"No track surface {'below' if drop else 'at'} object {key}; selection was not changed")
            data = bytearray(raw)
            struct.pack_into(">h", data, 4, height)
            result[key] = bytes(data)
        return result

    @Slot(str, object)
    def _placement_operation(self, kind: str, value: object) -> None:
        self._commit_editor()
        objects = self._selected_entries()
        session = self.edit_session
        if not objects or session is None:
            return
        try:
            if kind == "copy_position":
                self._copied_position = objects[0].position
                self.object_inspector.placement.message.setText(f"Copied position {self._copied_position}; Paste moves the existing selection without creating entries.")
                return
            if kind == "paste_position":
                if self._copied_position is None:
                    raise EditError("Copy a primary position first")
                entries = translated_entries(objects, tuple(a - b for a, b in zip(self._copied_position, objects[0].position)))
            elif kind == "align":
                entries = aligned_entries(objects, int(value))
            elif kind == "drop":
                entries = self._surface_entries({obj.key: obj.raw_data for obj in objects}, drop=True)
            elif kind == "rotate":
                axis, degrees = value
                entries = rotated_entries(objects, int(axis), float(degrees))
            elif kind == "scale":
                entries = scaled_entries(objects, float(value))
            else:
                raise EditError("Unknown placement operation")
            changed = session.apply_entries(entries, f"{kind.replace('_', ' ').title()} {len(objects)} object(s)")
            self._refresh_edits(objects[0].key)
            self.object_inspector.placement.message.setText("Placement applied as one undo step." if changed else "Selection already matches; no edit made.")
        except ValueError as error:
            self.object_inspector.placement.message.setText(f"Placement rejected: {error}")

    @Slot(int)
    def _select_segment(self, index: int) -> None:
        self.viewport.set_selected_segment(index)
        if self.selected_level is not None and self.current_model is not None:
            self.object_inspector.show_level(self.selected_level)
            self.object_inspector.show_model(self.current_model, selected_segment=index)

    def _update_edit_actions(self) -> None:
        self._update_placement()
        session = self.edit_session
        self.course_names_action.setEnabled(session is not None)
        self.global_objects_action.setEnabled(session is not None)
        self.model_editor_action.setEnabled(session is not None)
        self.course_builder_action.setEnabled(session is not None and self.selected_level is not None and self.current_model is not None)
        self.export_report_action.setEnabled(session is not None)
        if session is None:
            self._budget_label.clear()
        elif session.moving_key is None:
            report = session.export_report()
            self._budget_label.setText(f"ROM free: {report.remaining_bytes / 1024:.1f} KiB" if report.can_export else "ROM export blocked")
            self._budget_label.setToolTip(report.summary + "\nFile → ROM Budget and Project Changes")
        for action in (self.save_project_action, self.save_project_as_action, self.save_rom_action):
            action.setEnabled(session is not None)
        self.undo_action.setEnabled(session is not None and session.can_undo)
        self.redo_action.setEnabled(session is not None and session.can_redo)
        self.undo_action.setText("Undo " + session.undo_label if session is not None and session.can_undo else "Undo")
        self.redo_action.setText("Redo " + session.redo_label if session is not None and session.can_redo else "Redo")
        self.revert_object_action.setEnabled(session is not None and 0 <= self.viewport.selected_object < len(self.current_objects))
        self.add_object_action.setEnabled(session is not None and self.selected_level is not None)
        self.duplicate_objects_action.setEnabled(session is not None and bool(self._selected_entries()))
        self.delete_objects_action.setEnabled(session is not None and bool(self._selected_entries()))
        self.setWindowModified(session is not None and session.dirty)

    def _refresh_edits(self, key: ObjectKey | None, *, position_only: bool = False) -> None:
        if self.selected_level is None or self.edit_session is None:
            return
        header = self.selected_level.header
        selected_keys = {obj.key for obj in self._selected_entries()}
        maps = tuple(dict.fromkeys(i for i in (header.object_map_id, header.secondary_object_map_id) if i >= 0))
        objects = tuple(obj for map_id in maps for obj in self.edit_session.current_map(map_id).objects)
        selection = next((i for i,obj in enumerate(objects) if obj.key == key), -1)
        if selection < 0 and 0 <= self.viewport.selected_object < len(self.current_objects):
            old_key = self.current_objects[self.viewport.selected_object].key
            selection = next((i for i,obj in enumerate(objects) if obj.key == old_key), -1)
        self.current_objects = objects
        if position_only and not any(obj.definition.behavior_id in (13, 16) for obj in objects if obj.key in selected_keys):
            paths = self.viewport.paths
        else:
            paths = build_race_paths(objects, header.checkpoint_sets, vehicle=int(self.toolbar.vehicle.currentData()), lane=int(self.toolbar.lane.currentData()))
        visible = self.viewport.visible_objects
        self.viewport.set_objects(objects, paths)
        self.toolbar.set_object_count(len(objects))
        if position_only:
            self.viewport.set_visible_objects(visible)
            self.object_inspector.preview_position(objects, selection)
        else:
            self.object_inspector.replace_objects(objects, selection)
        indices = tuple(i for i, obj in enumerate(objects) if obj.key in selected_keys)
        if selection >= 0 and selection not in indices:
            indices = (selection,)
        self.viewport.set_selection(indices, selection)
        self.object_inspector.set_selection(indices, selection)
        if position_only:
            sprites = tuple(replace(sprite,position=objects[sprite.object_index].position)
                            if sprite.position != objects[sprite.object_index].position else sprite for sprite in self.current_sprites)
        else:
            sprites = load_level_sprites(self.art_source, objects, self._sprite_cache, self._sprite_texture_cache)+self._animation_sprites()
        if sprites != self.current_sprites:
            self.current_sprites = sprites
            self.viewport.set_sprites(sprites)
        self.toolbar.set_sprite_count(len(self.current_sprites))
        self._update_model_artwork()
        self._update_edit_actions()
        if self.image_browser is not None:
            self.image_browser.refresh_context()

    def _select_object_keys(self, keys: tuple[ObjectKey, ...]) -> None:
        indices = tuple(i for key in keys for i, obj in enumerate(self.current_objects) if obj.key == key)
        primary = indices[0] if indices else -1
        self.viewport.set_selection(indices, primary)
        self.object_inspector.set_selection(indices, primary, reveal=True)
        self._update_placement()

    def _structure_result(self, keys: tuple[ObjectKey, ...]) -> None:
        self._refresh_edits(keys[0] if keys else None)
        self._select_object_keys(keys)
        message = '\n'.join(self.edit_session.structure_warnings)
        warnings = self.edit_session.structure_warnings
        summary = '\n'.join(warnings[:2])
        if len(warnings) > 2:
            summary += f'\n{len(warnings)-2} additional reference notice(s); hover for details.'
        self.object_inspector.edit_message.setText('Edit applied. Ctrl+Z undo. ' + summary)
        self.object_inspector.edit_message.setToolTip(message)
        self.statusBar().showMessage(self.edit_session.undo_label + ' - Ctrl+Z to undo.', 9000)

    def _add_object(self) -> None:
        self._commit_editor()
        self.viewport.finish_object_drag()
        if self.edit_session is None or self.selected_level is None:
            return
        selected = self._selected_entries()
        position = selected[0].position if selected else tuple(int(np.clip(round(float(v)), -32768, 32767)) for v in self.viewport.camera.target)
        dialog = ObjectPalette(self.edit_session, self.selected_level.index, position, self)
        if dialog.exec() == ObjectPalette.DialogCode.Accepted:
            try:
                key = self.edit_session.add_object(int(dialog.map.currentData()), dialog.template(), dialog.position())
                self._structure_result((key,))
            except (ValueError, OSError) as error:
                self.object_inspector.edit_message.setText(str(error))
                self.statusBar().showMessage(str(error), 10000)
        dialog.deleteLater()

    def _duplicate_objects(self) -> None:
        self._commit_editor()
        self.viewport.finish_object_drag()
        if self.edit_session is None or not self._selected_entries():
            return
        try:
            keys = self.edit_session.duplicate_objects(tuple(obj.key for obj in self._selected_entries()),
                (self.object_inspector.move_step.value(), 0, 0))
            self._structure_result(keys)
        except (ValueError, OSError) as error:
            self.object_inspector.edit_message.setText(str(error))

    def _delete_objects(self) -> None:
        self._commit_editor()
        self.viewport.finish_object_drag()
        if self.edit_session is None or not self._selected_entries():
            return
        try:
            self.edit_session.delete_objects(tuple(obj.key for obj in self._selected_entries()))
            self._structure_result(())
        except (ValueError, OSError) as error:
            self.object_inspector.edit_message.setText(str(error))

    @Slot(object, str, object, object)
    def _apply_edit(self, key: ObjectKey, kind: str, field: object, value: object) -> None:
        self.viewport.finish_object_drag()
        session = self.edit_session
        if session is None:
            return
        try:
            selected = self._selected_entries()
            if kind == "position" and len(selected) > 1 and key in {obj.key for obj in selected}:
                primary = session.object(key)
                target = list(value) if field is None else list(primary.position)
                if field is not None:
                    target[int(field)] = value
                delta = tuple(a - b for a, b in zip(target, primary.position))
                changed = session.apply_entries(translated_entries(selected, delta), "Move selection")
            elif kind == "position" and field is None:
                changed = session.set_position(key, value)
            elif kind == "position":
                position = list(session.object(key).position)
                position[int(field)] = value
                changed = session.set_position(key, tuple(position))
            elif kind == "parameter":
                if len(selected) > 1 and self.object_inspector.placement.group_properties.isChecked():
                    changed = session.apply_entries(shared_parameter_entries(selected, str(field), value), f"Selection: {field}")
                else:
                    changed = session.set_parameter(key, str(field), value)
            elif kind == "raw":
                changed = session.set_raw_byte(key, field, value)
            elif kind == "bit":
                offset, bit = field
                current = session.object(key).raw_data[offset]
                changed = session.set_raw_byte(key, offset, current | (1<<bit) if value else current & ~(1<<bit))
            else:
                raise EditError("Unknown edit operation")
            self._refresh_edits(key)
            if changed:
                self.object_inspector.edit_message.setText("Edit applied. Ctrl+Z undoes the change.")
                self.statusBar().showMessage(f"{session.undo_label} · map {key[0]}, entry {key[1]} · {len(session.modified_maps)} modified map(s)", 5000)
        except (ValueError, OSError) as error:
            self._refresh_edits(key)
            self.object_inspector.edit_message.setText(f"Edit rejected: {error}")
            self.statusBar().showMessage(f"Edit rejected: {error}", 8000)

    @Slot(int, int)
    def _nudge_selected(self, axis: int, amount: int) -> None:
        self._nudge_object(self.viewport.selected_object, axis, amount)

    @Slot(int)
    def _begin_mouse_move(self, index: int) -> None:
        if self.edit_session is None or not 0 <= index < len(self.current_objects):
            self.viewport.finish_object_drag(cancel=True)
            return
        try:
            self.object_inspector.research.flush()
            self._drag_objects = self._selected_entries()
            self._lane_drag = self.viewport.route_lane
            if self._lane_drag >= 0:
                self._drag_objects = self._drag_objects[:1]
            self.edit_session.begin_group(tuple(obj.key for obj in self._drag_objects), f"{self.viewport.transform_mode} {len(self._drag_objects)} object(s)")
        except ValueError as error:
            self.viewport.finish_object_drag(cancel=True)
            self.statusBar().showMessage(str(error), 8000)

    @Slot(object)
    def _preview_mouse_move(self, position: tuple[int, int, int]) -> None:
        session = self.edit_session
        if session is not None and session.moving_key is not None:
            try:
                if self._lane_drag >= 0:
                    obj = self._drag_objects[0]
                    if session.preview_group({obj.key: lane_entry(obj, self._lane_drag, position)}):
                        self._refresh_edits(obj.key)
                    return
                delta = tuple(a - b for a, b in zip(position, self._drag_objects[0].position))
                entries = translated_entries(self._drag_objects, delta)
                if self.object_inspector.placement.surface.isChecked() and self.viewport._drag.axis != 1:
                    entries = self._surface_entries(entries, drop=False)
                if session.preview_group(entries):
                    self._refresh_edits(session.moving_key, position_only=True)
            except ValueError as error:
                self.viewport.finish_object_drag(cancel=True)
                self.statusBar().showMessage(str(error), 8000)

    @Slot(str, int, float)
    def _preview_transform(self, kind: str, axis: int, value: float) -> None:
        session = self.edit_session
        if session is None or not session.group_active:
            return
        try:
            entries = rotated_entries(self._drag_objects, axis, value) if kind == "Rotate" else scaled_entries(self._drag_objects, value)
            if session.preview_group(entries):
                self._refresh_edits(session.moving_key)
        except ValueError as error:
            self.viewport.finish_object_drag(cancel=True)
            self.object_inspector.placement.message.setText(f"Transform cancelled: {error}")

    @Slot(bool)
    def _finish_mouse_move(self, cancel: bool) -> None:
        session = self.edit_session
        if session is not None and session.moving_key is not None:
            key = session.moving_key
            changed = session.finish_group(cancel=cancel) if session.group_active else session.finish_move(cancel=cancel)
            self._drag_objects = ()
            self._lane_drag = -1
            self._refresh_edits(key)
            if cancel or changed:
                self.statusBar().showMessage("Mouse move cancelled" if cancel else f"Moved object · map {key[0]}, entry {key[1]}", 5000)

    @Slot(int, int, int)
    def _nudge_object(self, index: int, axis: int, amount: int) -> None:
        if not 0 <= index < len(self.current_objects):
            return
        obj = self.current_objects[index]
        position = list(obj.position)
        position[axis] += amount
        self._apply_edit(obj.key, "position", None, tuple(position))

    @Slot()
    def _undo(self) -> None:
        self._commit_editor()
        self.object_inspector.materials.cancel_preview()
        if self.edit_session is not None:
            key = self.edit_session.undo()
            if self.edit_session.last_asset_key is not None:
                self._refresh_asset()
            else:
                self._refresh_edits(key)
                self._select_object_keys(self.edit_session.last_keys)
            if key is not None: self.statusBar().showMessage(f"Undid edit · map {key[0]}, entry {key[1]}", 5000)

    @Slot()
    def _redo(self) -> None:
        self._commit_editor()
        self.object_inspector.materials.cancel_preview()
        if self.edit_session is not None:
            key = self.edit_session.redo()
            if self.edit_session.last_asset_key is not None:
                self._refresh_asset()
            else:
                self._refresh_edits(key)
                self._select_object_keys(self.edit_session.last_keys)
            if key is not None: self.statusBar().showMessage(f"Redid edit · map {key[0]}, entry {key[1]}", 5000)

    @Slot()
    def _revert_selected(self) -> None:
        self._commit_editor()
        index = self.viewport.selected_object
        if self.edit_session is not None and 0 <= index < len(self.current_objects):
            key = self.current_objects[index].key
            self.edit_session.revert_object(key)
            self._refresh_edits(key)

    def _commit_editor(self) -> None:
        """Commit the active cell/spinbox and its queued edit before save/history."""
        if getattr(self, '_committing_editor', False):
            return
        self._committing_editor = True
        try:
            self.viewport.finish_object_drag()
            focus = QApplication.focusWidget()
            # Viewport clicks also commit cells; releasing its focus here would
            # cancel the surface/route picker handling that same click.
            if focus is not None and focus is not self.viewport and self.isAncestorOf(focus):
                focus.clearFocus()
            flush_edits(self)
            self.object_inspector.research.flush()
        finally:
            self._committing_editor = False

    def _confirm_unsaved(self) -> bool:
        self._commit_editor()
        if self.edit_session is None or not self.edit_session.dirty:
            return True
        answer = QMessageBox.warning(self, "Unsaved edits", "Save your project before continuing?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        return self._save_project() if answer == QMessageBox.StandardButton.Save else True

    @Slot()
    def _choose_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open project", str(self._last_directory), "DKR Projects (*.dkrproj)")
        if path:
            self.load_project(Path(path))

    def load_project(self, path: Path, *, show_errors: bool = True) -> bool:
        try:
            base = self.edit_session.rom.source_path if self.edit_session is not None else None
            session = EditSession.load_project(path, base_path=base)
        except (OSError, ValueError) as error:
            if show_errors:
                QMessageBox.warning(self, "Cannot load project", str(error))
            return False
        if not self._confirm_unsaved():
            return False
        # Save may have just updated the same project being reopened.
        try:
            session = EditSession.load_project(path, base_path=base)
        except (OSError, ValueError) as error:
            if show_errors:
                QMessageBox.warning(self, "Cannot load project", str(error))
            return False
        rom_path = session.rom.source_path
        if rom_path is None:
            if show_errors:
                QMessageBox.warning(self, "Cannot load project", "The project does not have a ROM source path.")
            return False
        if not self._load_catalog(rom_path, extracted=False, show_errors=show_errors, discard_confirmed=True):
            return False
        self.edit_session = session
        self.object_database = session.database
        self._reset_image_cache()
        self.object_inspector.level_settings.session = session
        self._refresh_course_names()
        self.level_panel.select_level(session.selected_level)
        self._select_level(session.selected_level)
        self._update_edit_actions()
        self.statusBar().showMessage(f"Opened {path.name} · {len(session.modified_maps)} modified map(s)", 8000)
        return True

    @Slot()
    def _save_project(self, *, save_as: bool = False) -> bool:
        self._commit_editor()
        session = self.edit_session
        if session is None:
            return False
        path = None if save_as else session.project_path
        if path is None:
            chosen, _ = QFileDialog.getSaveFileName(self, "Save project", str(self._last_directory / "course-project.dkrproj"), "DKR Projects (*.dkrproj)")
            if not chosen:
                return False
            path = Path(chosen)
            if not path.suffix: path = path.with_suffix(".dkrproj")
        try:
            self.save_project_to(path)
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Cannot save project", str(error))
            return False
        return True

    def save_project_to(self, path: Path) -> Path:
        self._commit_editor()
        if self.edit_session is None:
            raise EditError("Open an original Rev 1 ROM to edit objects")
        result = self.edit_session.save_project(path, self.selected_level.index if self.selected_level else 0)
        self._last_directory = result.parent
        self._update_edit_actions()
        self.statusBar().showMessage(f"Saved project: {result.name}", 8000)
        return result

    @Slot()
    def _show_export_report(self) -> None:
        self._commit_editor()
        if self.edit_session is not None:
            ExportReportDialog(self.edit_session.export_report(), self, structural=audit_session(self.edit_session),
                               runtime_source=self.edit_session.rom).exec()

    @Slot()
    def _choose_save_rom(self) -> None:
        self._commit_editor()
        if self.edit_session is None:
            return
        base = self.edit_session.rom.source_path
        name = (base.stem if base is not None else "DKR") + " - edited.z64"
        chosen, _ = QFileDialog.getSaveFileName(self, "Save edited ROM as a new file", str(self._last_directory / name), "Big-endian N64 ROM (*.z64)")
        if chosen:
            path = Path(chosen)
            if not path.suffix: path = path.with_suffix(".z64")
            try:
                result = self.edit_session.save_rom(path)
                self.statusBar().showMessage(f"Saved edited ROM: {result.name}. Reopen your .dkrproj to continue editing.", 12000)
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, "Cannot save edited ROM", str(error))

    @Slot()
    def _choose_export(self) -> None:
        if self.current_model is None or self.selected_level is None:
            return
        name = re.sub(r"[^\w .'-]+", "_", self.selected_level.name).strip(". ") or "track"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export complete track as Wavefront OBJ", str(self._last_directory / f"{name}.obj"),
            "Wavefront OBJ (*.obj)",
        )
        if path:
            destination = Path(path)
            if destination.suffix.casefold() != ".obj":
                destination = destination.with_suffix(".obj")
            try:
                result = self.export_current(destination)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot export track", str(error))
                return
            self.statusBar().showMessage(
                f"Exported {result.segment_count} segments / {result.triangle_count:,} faces at 1:100 scale to {result.path}", 10000,
            )

    def export_current(self, destination: Path) -> ExportResult:
        if self.current_model is None:
            raise ModelError("No track geometry is loaded")
        helpers=None
        if self.edit_session is not None and self.edit_session.track_import_version(self.current_model.model_id)==10:
            helpers=collision_helper_faces(LevelModel.from_bytes(self.edit_session.track_base(self.current_model.model_id)))
        return export_obj(self.current_model, destination, textures=self.current_textures,helper_faces=helpers)

    @Slot(str)
    def _update_gpu_label(self, telemetry: str) -> None:
        renderer = self.viewport.gl_description.split(" | ")[-1].split("/")[0]
        self._gpu_label.setText("GPU: " + renderer)
        self._gpu_label.setToolTip(self.viewport.gl_description + "\nHelp → Graphics / GPU for details.")
        self._telemetry_label.setText(telemetry)
        if self.statusBar().currentMessage() == "Initializing OpenGL 3.3 Core…":
            self.statusBar().clearMessage()

    @Slot()
    def _show_graphics(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Graphics / GPU")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(self.viewport.gl_description)
        executable = getattr(sys, "_base_executable", sys.executable)
        dialog.setInformativeText(
            "Windows selects the GPU when Python starts. To use your RTX: open Settings → System → Display → Graphics, "
            "add the Python executable below, choose High performance (NVIDIA), save, then restart the viewer.\n\n"
            f"Python process: {executable}\nLaunch path: {sys.executable}\n\n"
            "This preference also applies to other apps using that Python executable."
        )
        settings = dialog.addButton("Open Windows Graphics Settings", QMessageBox.ButtonRole.ActionRole) if sys.platform == "win32" else None
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()
        if settings is not None and dialog.clickedButton() == settings:
            QDesktopServices.openUrl(QUrl("ms-settings:display-advancedgraphics"))

    @Slot()
    def _show_controls(self) -> None:
        QMessageBox.information(
            self, "Camera controls",
            "Click the viewport to focus it.\n\n"
            "Right mouse + movement: look\nAlt + right mouse: orbit\n"
            "Middle mouse + drag: pan in any view\n"
            "W/S: forward / backward\nA/D: strafe left / right\n"
            "Q/E: down / up\nShift: 4× speed\nWheel: zoom\nF: fit / reset\n"
            "Camera speed slider: 1–400% of normal level speed\n"
            "Selection, object focus and Fit/Reset keep movement speed unchanged.\n"
            "Escape: cancel a drag or release mouse capture\n\n"
            "Ctrl-click objects/list rows: multi-select\n"
            "View: Perspective / Top / Front / Right\n"
            "Grid arrow: automatic visibility, follow selection, or click a surface to set the plane\n"
            "Grid spacing uses game units. Axes toggles the corner orientation indicator.\n"
            "Transform: Move / supported Rotate / Scale; Ctrl-drag snaps\n"
            "Tools → Placement: group properties, surface placement and alignment\n"
            "Tools → Routes: existing lane points and directed AI links\n"
            "Geometry: vertex/face XYZ editing; Edit face material opens its batch texture\n"
            "Geometry → Verify stock rebuild: validation report and original-ROM stock export\n"
            "Geometry → Import OBJ: spatial segments, MTL/PNG artwork, material surfaces and resource report\n"
            "Geometry → Materials: pick a batch, choose a material, then Preview / Apply\n"
            "Tools → Minimap: sprite/marker alignment, Adventure 1/2 and tint; Apply stores drafts\n"
            "Tools → Cinematics: actor/camera paths, node timing/edits and optional camera preview",
        )

    @Slot()
    def _show_about(self) -> None:
        source = self.catalog.source if self.catalog is not None else None
        dialog = AboutDialog(version=__version__, parent=self,
                             source=source if isinstance(source, RomImage) else None)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    @Slot(str)
    def _show_render_error(self, error: str) -> None:
        self.statusBar().showMessage(f"OpenGL error: {error}")
        self._telemetry_label.setText("Render error")
        self._telemetry_label.setStyleSheet("color: #ff9595;")

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_unsaved():
            event.ignore()
            return
        self.object_inspector.materials.cancel_preview()
        self.viewport.clearFocus()
        self.viewport.cleanup()
        super().closeEvent(event)
