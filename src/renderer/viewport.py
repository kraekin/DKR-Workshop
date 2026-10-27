"""OpenGL scene viewport, editing overlays and camera input loop."""

from __future__ import annotations

import ctypes
import logging
import math
import time
import copy
from dataclasses import replace

import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCursor, QFocusEvent, QHideEvent, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel, QWidget

from src.renderer.camera import (Camera, FloatArray, screen_ray, ray_sphere_distance,
                                 TranslationDrag, translation_length, pick_translation_handle, ray_sprite_distance)
from src.renderer.camera import ScalarDrag, pick_rotation_handle, project_point, pick_track_vertex
from src.core.objects import LevelObject, RacePath
from src.core.routes import lane_point
from src.core.placement import TerrainSurface
from src.core.materials import pick_track_face
from src.renderer.gizmos import GizmoMesh, TranslationGizmo
from src.core.level_model import LevelModel
from src.core.textures import Texture, SpriteInstance
from src.core.object_models import ObjectLibrary, ModelInstance, ray_model_distance
from src.renderer.object_mesh import ObjectMesh, instance_pose
from src.core.special_art import SpecialInstance
from src.renderer.special_mesh import SpecialMesh
from src.renderer.environment import EnvironmentRenderer
from src.core.environment import WaterPreview, ScrollRates
from src.core.cinematics import CinematicTimeline, CinematicPose, path_points, look_at, camera_view
from src.core.level_header import LevelHeader
from src.core.objects import ObjectDefinition
from src.renderer.shaders import LINE_FRAGMENT_SHADER, LINE_VERTEX_SHADER
from src.renderer.track_mesh import TrackMesh, SpriteMesh
from src.renderer.transparency import TransparentDraw, draw_back_to_front
from src.renderer.work_grid import OrientationIndicator, grid_lines, grid_spacing

LOGGER = logging.getLogger(__name__)
MOVEMENT_KEYS: frozenset[int] = frozenset((
    Qt.Key.Key_W, Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D,
    Qt.Key.Key_Q, Qt.Key.Key_E, Qt.Key.Key_Shift,
))


class Viewport(QOpenGLWidget):
    grid_changed = Signal(bool)
    grid_follow_changed = Signal(bool)
    preview_time_changed = Signal(float)
    cinematic_camera_released = Signal()
    status_changed = Signal(str)
    render_failed = Signal(str)
    object_selected = Signal(int)
    object_nudged = Signal(int, int, int)
    prepare_pointer_selection = Signal()
    object_drag_started = Signal(int)
    transform_drag_preview = Signal(str, int, float)
    object_drag_preview = Signal(object)
    object_drag_finished = Signal(bool)
    route_lane_selected = Signal(int)
    route_target_picked = Signal(int)
    track_face_picked = Signal(int, int)
    geometry_picked = Signal(int, int, bool)
    surface_picked = Signal(object)
    geometry_drag_started = Signal()
    geometry_drag_preview = Signal(object)
    geometry_drag_finished = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("referenceViewport")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(420, 300)
        self.camera = Camera()
        self.bounds_min: FloatArray = np.array([-20.0, 0.0, -20.0], dtype=np.float32)
        self.bounds_max: FloatArray = np.array([20.0, 10.0, 20.0], dtype=np.float32)
        self.camera_speed_percent = 100
        self._scene_camera_speed = float(np.linalg.norm(self.bounds_max-self.bounds_min)) * 0.4
        self.set_camera_speed(self.camera_speed_percent)
        self.show_grid = False
        self.show_axes = True
        self._grid_preference: bool | None = None
        self.grid_follow_selection = True
        self.grid_origin = np.zeros(3, np.float32)
        self.grid_pick = False
        self._grid_key: tuple | None = None
        self._grid_surface: tuple | None = None
        self._grid_auto_origin_pending = False
        self.orientation = OrientationIndicator(self)
        self.grid_label = QLabel(self)
        self.grid_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.grid_label.setStyleSheet('color: #bccbdc; background: #1b2634; padding: 3px 6px;')
        self.grid_label.hide()
        self.model: LevelModel | None = None
        self.textures: dict[int, Texture] = {}
        self.textured = True
        self._mesh: TrackMesh | None = None
        self._mesh_dirty = False
        self._geometry_mesh_dirty = False
        self.sprites: tuple[SpriteInstance, ...] = ()
        self.show_sprites = True
        self._sprite_mesh: SpriteMesh | None = None
        self._sprites_dirty = False
        self.object_library: ObjectLibrary | None = None
        self.model_instances: tuple[ModelInstance,...] = ()
        self.show_models = True
        self._object_mesh: ObjectMesh | None = None
        self._object_mesh_dirty = False
        self.special_instances: tuple[SpecialInstance, ...] = ()
        self.show_special_art = True
        self._special_mesh: SpecialMesh | None = None
        self._special_dirty = False
        self._environment: EnvironmentRenderer | None = None
        self.environment_header: LevelHeader | None = None
        self.environment_sky: ObjectDefinition | None = None
        self.environment_library: ObjectLibrary | None = None
        self.environment_water: WaterPreview | None = None
        self.environment_flash: Texture | None = None
        self.environment_rates: ScrollRates = {}
        self._environment_dirty = False
        self.preview_sky = True
        self.preview_fog = False
        self.preview_texture_motion = True
        self.preview_water = True
        self.preview_gradient = False
        self.preview_time = 0.0
        self.preview_playing = False
        self.preview_rate = 1.0
        self.preview_clip = -1
        self.preview_duration = 30.0
        self.cinematic_motion = True
        self.show_cinematic_paths = False
        self.cinematics: tuple[CinematicTimeline, ...] = ()
        self.cinematic_poses: dict[int, CinematicPose] = {}
        self.cinematic_camera = -1
        self._saved_cinematic_camera: Camera | None = None
        self._cinematic_gizmos: GizmoMesh | None = None
        self._cinematic_paths: tuple[RacePath, ...] = ()
        self._cinematic_dirty = False
        self._cinematic_sample_key: object = None
        self.display_models: tuple[ModelInstance, ...] = ()
        self.display_sprites: tuple[SpriteInstance, ...] = ()
        self.objects: tuple[LevelObject, ...] = ()
        self.paths: tuple[RacePath, ...] = ()
        self.visible_objects: tuple[int, ...] = ()
        self.selected_object = -1
        self.selected_objects: tuple[int, ...] = ()
        self.transform_mode = "Move"
        self.rotation_axes: tuple[int, ...] = ()
        self.scale_supported = False
        self.grid_snap = False
        self.route_lane = -1
        self.material_active = False
        self.material_isolation: tuple[int, int] | None = None
        self.material_picking = False
        self.material_faces: tuple[tuple[int, int], ...] = ()
        self.material_vertices: tuple[tuple[int, int], ...] = ()
        self.geometry_active = False
        self.geometry_faces = False
        self.geometry_segment = -1
        self.geometry_picking = False
        self.surface_picker: TerrainSurface | None = None
        self.geometry_center: FloatArray | None = None
        self.geometry_step = 16
        self._drag_is_geometry = False
        self.route_pick_slot: int | None = None
        self.object_move_mode = False
        self.object_move_step = 16
        self.mouse_move_enabled = False
        self._drag: TranslationDrag | ScalarDrag | None = None
        self._drag_press = QPoint()
        self._drag_moved = False
        self._hover_handle: int | None = None
        self._translation_gizmo: TranslationGizmo | None = None
        self.show_objects = True
        self.show_racelines = False
        self.marker_radius = 30.0
        self._gizmos: GizmoMesh | None = None
        self._gizmos_dirty = False
        self.vertex_colors = True
        self.wireframe = False
        self.show_segment_bounds = False
        self.cull_backfaces = True
        self.selected_segment = -1
        self.isolate_segment = False
        self._keys: set[int] = set()
        self._looking = False
        self._orbiting = False
        self._panning = False
        self._pan_position = QPointF()
        self._cursor_before_look = QPoint()
        self._program = 0
        self._vao = 0
        self._vbo = 0
        self._uniform = -1
        self._grid_count = 0
        self.frame_count = 0
        self.framebuffer_samples = 0
        self.gl_description = "Waiting for OpenGL context"
        self.render_error: str | None = None
        self._last_tick = time.perf_counter()
        self._last_report = self._last_tick
        self._frames_at_report = 0
        self.hud = QLabel(self)
        self.hud.setTextFormat(Qt.TextFormat.PlainText)
        self.hud.move(18, 18)
        self.hud.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hud.setStyleSheet("color: #b5c4d5; background: transparent; font-size: 12px;")
        self.hud.setText(
            "Open a ROM to begin\n"
            "RMB look · MMB pan · WASD fly · Q/E vertical · Shift boost\n"
            "Alt + RMB orbit · Wheel zoom · F fit · Esc release\n"
            "X red   Y green   Z blue"
        )
        self.hud.adjustSize()
        self.lane_labels: list[QLabel] = []
        for lane in range(4):
            label = QLabel(str(lane), self)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedSize(22, 22)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setStyleSheet("color: white; background: #125b79; border: 2px solid #6ee7ff; border-radius: 10px;")
            label.hide()
            self.lane_labels.append(label)
        self.reset_camera()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def initializeGL(self) -> None:
        try:
            context = self.context()
            if context is None or not context.isValid():
                raise RuntimeError("Qt did not create a valid OpenGL context")
            fmt = context.format()
            if (fmt.majorVersion(), fmt.minorVersion()) < (3, 3):
                raise RuntimeError("OpenGL 3.3 or newer is required")
            if fmt.profile() != fmt.OpenGLContextProfile.CoreProfile:
                raise RuntimeError("A Core Profile OpenGL context is required")
            context.aboutToBeDestroyed.connect(self.cleanup)
            self._environment = EnvironmentRenderer()
            self._environment_dirty = True
            version = GL.glGetString(GL.GL_VERSION).decode("ascii", errors="replace")
            renderer = GL.glGetString(GL.GL_RENDERER).decode("ascii", errors="replace")
            self.gl_description = f"OpenGL {version} | {renderer}"
            LOGGER.info("%s | depth %s | default surface samples %s", self.gl_description,
                        fmt.depthBufferSize(), fmt.samples())
            self._program = int(compileProgram(
                compileShader(LINE_VERTEX_SHADER, GL.GL_VERTEX_SHADER),
                compileShader(LINE_FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER),
            ))
            vertices = np.empty((0, 6), np.float32)
            self._vao = int(GL.glGenVertexArrays(1))
            self._vbo = int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self._vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_STATIC_DRAW)
            for index, offset in ((0, 0), (1, 12)):
                GL.glEnableVertexAttribArray(index)
                GL.glVertexAttribPointer(index, 3, GL.GL_FLOAT, GL.GL_FALSE, 24, ctypes.c_void_p(offset))
            GL.glBindVertexArray(0)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            self._uniform = int(GL.glGetUniformLocation(self._program, "u_view_projection"))
            self._grid_uniforms = {name: int(GL.glGetUniformLocation(self._program, name))
                                   for name in ('u_grid', 'u_grid_center', 'u_grid_radius')}
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_MULTISAMPLE)
            GL.glClearColor(0.045, 0.063, 0.086, 1.0)
            self._check_gl()
            self.status_changed.emit("Initializing viewport…")
        except Exception as error:
            self._fail(error)

    def paintGL(self) -> None:
        if self.render_error is not None:
            return
        try:
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            if not self._program:
                return
            if self.frame_count == 0:
                # Qt's multisampling belongs to the widget FBO, not the window surface.
                self.framebuffer_samples = int(GL.glGetIntegerv(GL.GL_SAMPLES))
                LOGGER.info("Widget framebuffer: %s samples", self.framebuffer_samples)
            if self._mesh_dirty:
                mesh = TrackMesh(self.model, self.textures) if self.model is not None else None
                if self._mesh is not None:
                    self._mesh.delete()
                self._mesh = mesh
                self._mesh_dirty = False
            if self._geometry_mesh_dirty:
                if self._mesh is not None and self.model is not None:
                    self._mesh.update_geometry(self.model)
                self._geometry_mesh_dirty = False
            self._sample_cinematics()
            view = self.camera.view_matrix()
            matrix = self.camera.projection_matrix(self.width() / max(self.height(), 1)) @ view
            if self._sprites_dirty:
                if self._sprite_mesh is None or not self._sprite_mesh.update_positions(self.display_sprites):
                    sprites = SpriteMesh(self.display_sprites) if self.display_sprites else None
                    if self._sprite_mesh is not None:
                        self._sprite_mesh.delete()
                    self._sprite_mesh = sprites
                self._sprites_dirty = False
            isolated_material = self.material_active and self.material_isolation is not None
            isolated = self.material_isolation[0] if isolated_material else self.selected_segment if self.isolate_segment else -1
            if self._object_mesh_dirty:
                if self._object_mesh is not None:
                    self._object_mesh.delete()
                    self._object_mesh = None
                if self.object_library is not None and self.model_instances:
                    self._object_mesh = ObjectMesh(self.object_library,self.model_instances)
                self._object_mesh_dirty = False
            if self._special_dirty:
                if self._special_mesh is None or not self._special_mesh.update_instances(self.special_instances):
                    if self._special_mesh is not None:
                        self._special_mesh.delete()
                        self._special_mesh = None
                    if self.special_instances:
                        self._special_mesh = SpecialMesh(self.special_instances)
                self._special_dirty = False
            if self._gizmos_dirty and (self.show_objects or self.show_racelines):
                visible = self.visible_objects if self.show_objects else ()
                paths = self.paths if self.show_racelines else ()
                if self._gizmos is None or not self._gizmos.update_positions(self.objects,paths,self.marker_radius,visible):
                    gizmos = GizmoMesh(self.objects, paths, self.marker_radius, visible) if self.objects else None
                    if self._gizmos is not None:
                        self._gizmos.delete()
                    self._gizmos = gizmos
                self._gizmos_dirty = False
            if self._cinematic_dirty:
                if self._cinematic_gizmos is not None:
                    self._cinematic_gizmos.delete()
                visible = tuple(index for timeline in self.cinematics for index in timeline.track.indices)
                self._cinematic_gizmos = GizmoMesh(self.objects, self._cinematic_paths, self.marker_radius, visible) if visible else None
                self._cinematic_dirty = False
            if self._environment is not None:
                if self._environment_dirty:
                    self._environment.configure(self.environment_header, self.environment_library,
                        self.environment_sky, self.environment_water, self.textures, self.environment_flash)
                    self._environment_dirty = False
                self._environment.background(matrix, self.camera.position, self.camera.yaw, self.preview_time,
                    enabled=self.preview_sky, gradient=self.preview_gradient, textured=self.textured, motion=self.preview_texture_motion)
                self._environment.fog(self.preview_fog and self.camera.view == 'Perspective')
            water_active = self.preview_water and not self.material_active and self.environment_water is not None
            if self._mesh is not None:
                omitted = set(self.environment_water.faces) if water_active else set()
                if isolated_material:
                    omitted.update((s.index, i) for s in self.model.segments for i in range(len(s.batches))
                                   if (s.index, i) != self.material_isolation)
                self._mesh.update_environment(self.preview_time, self.preview_texture_motion, self.environment_rates,
                    omitted)
            # Opaque/cutout depth is complete before one scene-wide blended pass.
            if self._mesh is not None:
                self._mesh.draw(matrix, vertex_colors=self.vertex_colors, wireframe=self.wireframe,
                                cull_backfaces=self.cull_backfaces, isolated_segment=isolated,
                                textured=self.textured, camera_position=self.camera.position, transparent_pass=False)
            if self._sprite_mesh is not None and self.show_sprites and not isolated_material:
                self._sprite_mesh.draw(matrix, view, self.camera.position, transparent_pass=False, seconds=self.preview_time,
                    hidden=frozenset(owner for owner, pose in self.cinematic_poses.items() if not pose.visible),
                    upright_sceneries=self.camera.view == 'Perspective')
            if self._object_mesh is not None and self.show_models and not isolated_material:
                self._object_mesh.draw(self.display_models, matrix, self.camera.position, self.preview_time,
                    self.selected_object, self.preview_clip, textured=self.textured, wireframe=self.wireframe,
                    culling=self.cull_backfaces, transparent=False)
            if self._special_mesh is not None and self.show_special_art and not isolated_material:
                self._special_mesh.draw(matrix, self.camera.position, self.preview_time,
                    transparent=False, textured=self.textured, wireframe=self.wireframe)
            if water_active and self._environment is not None and not self.environment_water.settings.translucent:
                self._environment.draw_water(matrix, self.preview_time, textured=self.textured, wireframe=self.wireframe)
            self._draw_transparency(matrix, view, isolated, water_active)
            GL.glUseProgram(self._program)
            GL.glUniformMatrix4fv(self._uniform, 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
            if self.show_grid:
                self._draw_grid()
            self.orientation.set_view(view)
            if self._mesh is not None and self.show_segment_bounds:
                GL.glUniformMatrix4fv(self._uniform, 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
                self._mesh.draw_bounds(selected_segment=self.selected_segment, isolated_segment=isolated)
            if self._gizmos is not None and not isolated_material:
                self._gizmos.draw(matrix, self._uniform, objects=self.show_objects,
                                  paths=self.show_racelines, selected=self.selected_objects)
            if self._cinematic_gizmos is not None and self.show_cinematic_paths and not isolated_material:
                self._cinematic_gizmos.draw(matrix, self._uniform, objects=True, paths=True, selected=self.selected_objects)
            geometry_handle = self.geometry_active and self.geometry_picking and self.geometry_center is not None
            if geometry_handle or (not self.material_active and (self.mouse_move_enabled or self.route_lane >= 0) and 0 <= self.selected_object < len(self.objects)):
                center = self.geometry_center if geometry_handle else self.handle_center()
                length = translation_length(self.camera, center, self.height())
                if length is not None:
                    if self._translation_gizmo is None:
                        self._translation_gizmo = TranslationGizmo()
                    active = (-1 if self._drag.axis is None else self._drag.axis) if self._drag else self._hover_handle
                    self._translation_gizmo.draw(matrix, self._uniform, center, length, view, active,
                                                  mode="Move" if geometry_handle or self.route_lane >= 0 else self.transform_mode, axes=self.rotation_axes)
            self._position_lane_labels(matrix)
            if self.material_active and self._mesh is not None:
                if self.geometry_active and not self.geometry_faces:
                    self._mesh.draw_geometry_points(matrix, self._uniform, self.geometry_segment)
                self._mesh.draw_selection(matrix, self._uniform, self.material_faces, self.material_vertices)
            GL.glUseProgram(0)
            self._check_gl()
            self.frame_count += 1
        except Exception as error:
            self._fail(error)

    def _draw_transparency(self, matrix: FloatArray, view: FloatArray, isolated: int, water_active: bool) -> None:
        draws: list[TransparentDraw] = []
        isolated_material = self.material_active and self.material_isolation is not None
        if self._mesh is not None:
            draws.extend(self._mesh.transparent_draws(matrix, vertex_colors=self.vertex_colors, wireframe=self.wireframe,
                cull_backfaces=self.cull_backfaces, isolated_segment=isolated, textured=self.textured,
                camera_position=self.camera.position))
        if self._sprite_mesh is not None and self.show_sprites and not isolated_material:
            draws.extend(self._sprite_mesh.transparent_draws(matrix, view, self.camera.position, seconds=self.preview_time,
                hidden=frozenset(owner for owner, pose in self.cinematic_poses.items() if not pose.visible),
                upright_sceneries=self.camera.view == 'Perspective'))
        if self._object_mesh is not None and self.show_models and not isolated_material:
            draws.extend(self._object_mesh.transparent_draws(self.display_models, matrix, self.camera.position, self.preview_time,
                self.selected_object, self.preview_clip, textured=self.textured, wireframe=self.wireframe,
                culling=self.cull_backfaces))
        if self._special_mesh is not None and self.show_special_art and not isolated_material:
            draws.extend(self._special_mesh.transparent_draws(matrix, self.camera.position, self.preview_time,
                textured=self.textured, wireframe=self.wireframe))
        if water_active and self._environment is not None:
            draws.extend(self._environment.transparent_draws(matrix, self.preview_time,
                textured=self.textured, wireframe=self.wireframe))
        draw_back_to_front(draws, view)

    def _grid_terrain(self) -> TerrainSurface | None:
        if self.model is None:
            return None
        segment = self.selected_segment if self.isolate_segment else -1
        if self._grid_surface is None or self._grid_surface[0] is not self.model or self._grid_surface[1] != segment:
            self._grid_surface = self.model, segment, TerrainSurface.from_model(self.model, segment)
        return self._grid_surface[2]

    def reset_grid_plane(self) -> None:
        self.grid_origin = (self.bounds_min+self.bounds_max)*.5
        anchor = next((o for o in self.objects if o.definition.behavior_id == 13
                       and not o.value('isAltCheckpoint', 0) and o.value('index', -1) == 0), None)
        point = anchor.position if anchor else tuple(self.grid_origin)
        terrain = self._grid_terrain()
        height = terrain.surface_y(point, drop=anchor is not None) if terrain else None
        self.grid_origin[1] = height if height is not None else point[1]
        self.set_grid_follow_selection(True)

    def set_grid_follow_selection(self, enabled: bool) -> None:
        self.grid_follow_selection = enabled
        self.grid_follow_changed.emit(enabled)
        self.update()

    def begin_grid_placement(self) -> None:
        if self.model is None:
            return
        self.finish_object_drag(cancel=True)
        self.grid_pick = True
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.status_changed.emit('Click a track surface to position the working plane. Esc cancels.')

    def set_grid_automatic(self, enabled: bool) -> None:
        self._grid_preference = None if enabled else self.show_grid
        self.show_grid = self.camera.view != 'Perspective' if enabled else self.show_grid
        self.grid_label.setVisible(self.show_grid)
        self.grid_changed.emit(self.show_grid)
        self.update()

    def _draw_grid(self) -> None:
        center = self.camera.target.copy()
        point = self.grid_origin
        if self.grid_follow_selection:
            if self.geometry_active and self.geometry_center is not None:
                point = self.geometry_center
            elif 0 <= self.selected_object < len(self.objects):
                point = self.objects[self.selected_object].position
        normal = 2 if self.camera.view == 'Front' else 0 if self.camera.view == 'Right' else 1
        center[normal] = point[normal] + (.2 if normal == 1 else 0)
        distance = abs(float((center-self.camera.position) @ -self.camera.view_matrix()[2, :3]))
        span = self.camera.ortho_height if self.camera.view != 'Perspective' else max(
            2*distance*math.tan(math.radians(self.camera.fov)*.5), 16.)
        spacing = grid_spacing(span)
        key = tuple(center), spacing, self.camera.view
        if key != self._grid_key:
            vertices, spacing = grid_lines(center, span, self.camera.view)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_DYNAMIC_DRAW)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            self._grid_count = len(vertices)
            self._grid_key = key
        self.grid_label.setText(f'Grid {spacing:g} units · {"XYZ"[normal]} {point[normal]:g}')
        self.grid_label.adjustSize()
        GL.glUniform1i(self._grid_uniforms['u_grid'], 1)
        GL.glUniform3fv(self._grid_uniforms['u_grid_center'], 1, center)
        GL.glUniform1f(self._grid_uniforms['u_grid_radius'], spacing*24)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDepthMask(GL.GL_FALSE)
        if self.camera.view != 'Perspective':
            GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_LINES, 0, self._grid_count)
        GL.glBindVertexArray(0)
        GL.glUniform1i(self._grid_uniforms['u_grid'], 0)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)

    def resizeGL(self, width: int, height: int) -> None:
        # QOpenGLWidget sets its physical-pixel viewport, including HiDPI scaling.
        self.finish_object_drag(cancel=True)
        self.orientation.move(max(0, self.width()-108), max(0, self.height()-108))
        self.grid_label.move(18, max(0, self.height()-36))

    def _check_gl(self) -> None:
        error = GL.glGetError()
        if error != GL.GL_NO_ERROR:
            raise RuntimeError(f"OpenGL error 0x{error:04X}")

    def _fail(self, error: Exception) -> None:
        LOGGER.exception("Viewport rendering failed")
        self.render_error = str(error)
        self._release_input()
        self._timer.stop()
        self.hud.setText(f"OpenGL initialization/rendering failed\n{error}")
        self.hud.adjustSize()
        self.render_failed.emit(str(error))

    @Slot()
    def cleanup(self) -> None:
        context = self.context()
        if context is None or not context.isValid():
            return
        self.makeCurrent()
        try:
            if self._mesh is not None:
                self._mesh.delete()
                self._mesh = None
            if self._gizmos is not None:
                self._gizmos.delete()
                self._gizmos = None
            if self._cinematic_gizmos is not None:
                self._cinematic_gizmos.delete()
                self._cinematic_gizmos = None
            self._cinematic_dirty = bool(self.cinematics)
            if self._sprite_mesh is not None:
                self._sprite_mesh.delete()
                self._sprite_mesh = None
            if self._object_mesh is not None:
                self._object_mesh.delete()
                self._object_mesh = None
            self._object_mesh_dirty = bool(self.model_instances)
            if self._environment is not None:
                self._environment.delete()
                self._environment = None
            self._environment_dirty = True
            if self._special_mesh is not None:
                self._special_mesh.delete()
                self._special_mesh = None
            self._special_dirty = bool(self.special_instances)
            if self._translation_gizmo is not None:
                self._translation_gizmo.delete()
                self._translation_gizmo = None
            self._sprites_dirty = bool(self.sprites)
            self._gizmos_dirty = bool(self.objects)
            self._mesh_dirty = self.model is not None
            if self._vbo:
                GL.glDeleteBuffers(1, [self._vbo])
            if self._vao:
                GL.glDeleteVertexArrays(1, [self._vao])
            if self._program:
                GL.glDeleteProgram(self._program)
            self._vbo = self._vao = self._program = 0
            self._grid_key = None
        finally:
            self.doneCurrent()

    @Slot()
    def reset_camera(self) -> None:
        if self.cinematic_camera >= 0:
            self.release_cinematic_camera()
        minimum, maximum = self.bounds_min, self.bounds_max
        if self.model is not None and self.material_active and self.material_isolation is not None:
            s, b = self.material_isolation
            segment = self.model.segments[s]
            first, end = (*segment.batches, segment.terminal_batch)[b:b+2]
            points = segment.vertices[segment.indices[first.faces_offset:end.faces_offset]].reshape(-1, 3)
            if len(points):
                minimum, maximum = points.min(axis=0), points.max(axis=0)
        elif self.model is not None and self.isolate_segment and self.selected_segment >= 0:
            bounds = self.model.segments[self.selected_segment].geometry_bounds
            minimum, maximum = np.array(bounds.minimum, dtype=np.float32), np.array(bounds.maximum, dtype=np.float32)
        self.camera.fit_bounds(minimum, maximum, self.width() / max(self.height(), 1))
        self.update()

    @Slot(str)
    def set_view(self, name: str) -> None:
        if self.cinematic_camera >= 0:
            self.release_cinematic_camera()
        self._release_input()
        self.camera.set_view(name)
        self.show_grid = self._grid_preference if self._grid_preference is not None else name != 'Perspective'
        self.grid_label.setVisible(self.show_grid)
        self.grid_changed.emit(self.show_grid)
        self.update()

    @Slot(str)
    def set_transform_mode(self, name: str) -> None:
        self.finish_object_drag(cancel=True)
        self.transform_mode = name
        self._hover_handle = None
        self.update()

    @Slot(int)
    def set_camera_speed(self, percent: int) -> None:
        """Scale normal whole-scene speed independently of focus/framing."""
        self.camera_speed_percent = max(1, min(percent, 400))
        self.camera.speed = self._scene_camera_speed * self.camera_speed_percent / 100.0

    def set_model(self, model: LevelModel | None, textures: dict[int, Texture] | None = None) -> None:
        textures = textures or {}
        if self.model is not model or self.textures is not textures:
            self._mesh_dirty = True
        self.model = model
        self._grid_surface = None
        self.grid_follow_selection = True
        self._grid_auto_origin_pending = True
        self.textures = textures
        self.selected_segment = -1
        self.isolate_segment = False
        if model is None:
            self.bounds_min = np.array([-20.0, 0.0, -20.0], dtype=np.float32)
            self.bounds_max = np.array([20.0, 10.0, 20.0], dtype=np.float32)
        else:
            self.bounds_min = np.array(model.bounds.minimum, dtype=np.float32)
            self.bounds_max = np.array(model.bounds.maximum, dtype=np.float32)
        self.grid_origin = (self.bounds_min+self.bounds_max)*.5
        self.grid_origin[1] = self.bounds_min[1]
        radius = float(np.linalg.norm(self.bounds_max - self.bounds_min)) * 0.5
        self._scene_camera_speed = max(radius * 0.8, 1.0)
        self.set_camera_speed(self.camera_speed_percent)
        self.reset_camera()

    @Slot(bool)
    def set_textured(self, enabled: bool) -> None:
        self.textured = enabled
        self.update()

    def refresh_materials(self, model: LevelModel, textures: dict[int, Texture]) -> None:
        """Material-only replacement keeps framing, movement speed and segment isolation."""
        self.model, self.textures = model, textures
        self._mesh_dirty = True
        self.update()

    def refresh_geometry(self, model: LevelModel) -> None:
        self.model = model
        self.bounds_min = np.array(model.bounds.minimum, np.float32)
        self.bounds_max = np.array(model.bounds.maximum, np.float32)
        self._geometry_mesh_dirty = True
        self.update()

    def set_objects(self, objects: tuple[LevelObject, ...], paths: tuple[RacePath, ...]) -> None:
        self.objects = objects
        self.paths = paths
        self.visible_objects = tuple(range(len(objects)))
        self.selected_object = -1
        self.selected_objects = ()
        self.marker_radius = max(18.0, min(float(np.max(self.bounds_max-self.bounds_min)) / 150.0, 65.0))
        self._gizmos_dirty = True
        if self._grid_auto_origin_pending:
            self._grid_auto_origin_pending = False
            self.reset_grid_plane()
        self.update()

    def set_paths(self, paths: tuple[RacePath, ...]) -> None:
        self.paths = paths
        self._gizmos_dirty = True
        self.update()

    def set_sprites(self, sprites: tuple[SpriteInstance, ...]) -> None:
        self.sprites = sprites
        self._sprites_dirty = True
        self.update()

    @Slot(bool)
    def set_sprites_visible(self, enabled: bool) -> None:
        self.show_sprites = enabled
        self.update()

    @Slot(bool)
    def set_object_move_mode(self, enabled: bool) -> None:
        self.object_move_mode = enabled

    @Slot(int)
    def set_object_move_step(self, step: int) -> None:
        self.object_move_step = step

    @Slot(bool)
    def set_mouse_move_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.finish_object_drag(cancel=True)
        self.mouse_move_enabled = enabled
        self._hover_handle = None
        if not self._looking and not self._panning:
            self.unsetCursor()
        self.update()

    def translation_handle_at(self, x: float, y: float) -> int | None:
        if self.geometry_active:
            if not self.geometry_picking or self.geometry_center is None:
                return None
            center = self.geometry_center
            length = translation_length(self.camera, center, self.height())
            matrix = self.camera.projection_matrix(self.width()/max(self.height(), 1)) @ self.camera.view_matrix()
            return pick_translation_handle(x, y, center, length, matrix, self.width(), self.height()) if length is not None else None
        if self.material_active or not (self.mouse_move_enabled or self.route_lane >= 0) or not 0 <= self.selected_object < len(self.objects):
            return None
        center = self.handle_center()
        length = translation_length(self.camera, center, self.height())
        if length is None:
            return None
        matrix = self.camera.projection_matrix(self.width()/max(self.height(), 1)) @ self.camera.view_matrix()
        if self.transform_mode == "Rotate" and self.route_lane < 0:
            return pick_rotation_handle(x, y, center, length, self.rotation_axes, matrix, self.width(), self.height())
        if self.transform_mode == "Scale" and self.route_lane < 0:
            if not self.scale_supported:
                return None
            end = center + (self.camera.right + self.camera.view_matrix()[1, :3]) * length * .7
            for point in (center, end):
                pixel = project_point(point, matrix, self.width(), self.height())
                if pixel is not None and np.linalg.norm(np.array(pixel) - (x, y)) <= 12:
                    return -1
            return None
        return pick_translation_handle(x, y, center, length, matrix, self.width(), self.height())

    def handle_center(self) -> FloatArray:
        obj = self.objects[self.selected_object]
        return np.asarray(lane_point(obj, self.route_lane) if self.route_lane >= 0 and obj.definition.behavior_id == 13 else obj.position, np.float32)

    def _position_lane_labels(self, matrix: FloatArray) -> None:
        obj = self.objects[self.selected_object] if 0 <= self.selected_object < len(self.objects) else None
        for lane, label in enumerate(self.lane_labels):
            pixel = project_point(np.asarray(lane_point(obj, lane), np.float32), matrix, self.width(), self.height()) if self.route_lane >= 0 and obj and obj.definition.behavior_id == 13 else None
            visible = pixel is not None and 0 <= pixel[0] <= self.width() and 0 <= pixel[1] <= self.height()
            label.setVisible(visible)
            if visible:
                label.move(round(pixel[0]) - 11, round(pixel[1]) - 11)
                label.setText(f"[{lane}]" if lane == self.route_lane else str(lane))

    def lane_at(self, x: float, y: float) -> int | None:
        if self.route_lane < 0 or not 0 <= self.selected_object < len(self.objects):
            return None
        matrix = self.camera.projection_matrix(self.width() / max(self.height(), 1)) @ self.camera.view_matrix()
        hits = []
        for lane in range(4):
            pixel = project_point(np.asarray(lane_point(self.objects[self.selected_object], lane), np.float32), matrix, self.width(), self.height())
            if pixel is not None:
                distance = float(np.linalg.norm(np.asarray(pixel) - (x, y)))
                if distance <= 12:
                    hits.append((distance, lane != self.route_lane, lane))
        return min(hits)[2] if hits else None

    def finish_object_drag(self, *, cancel: bool = False) -> None:
        if self._drag is None:
            return
        self._drag = None
        self._drag_moved = False
        self._hover_handle = None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.unsetCursor()
        if self._drag_is_geometry:
            self._drag_is_geometry = False
            self.geometry_drag_finished.emit(cancel)
        else:
            self.object_drag_finished.emit(cancel)
        self.update()

    @Slot(object)
    def set_visible_objects(self, indices: tuple[int, ...]) -> None:
        self.visible_objects = tuple(index for index in indices if 0 <= index < len(self.objects))
        self._gizmos_dirty = True
        self.update()

    @Slot(bool)
    def set_objects_visible(self, enabled: bool) -> None:
        self.show_objects = enabled
        self._gizmos_dirty = True
        self.update()

    @Slot(bool)
    def set_racelines_visible(self, enabled: bool) -> None:
        self.show_racelines = enabled
        self._gizmos_dirty = True
        self.update()

    @Slot(int)
    def select_object(self, index: int) -> None:
        self.selected_object = index if 0 <= index < len(self.objects) else -1
        if index not in self.selected_objects:
            self.selected_objects = (index,) if self.selected_object >= 0 else ()
        self.update()

    def set_selection(self, indices: tuple[int, ...], primary: int) -> None:
        self.selected_objects = tuple(dict.fromkeys(i for i in indices if 0 <= i < len(self.objects)))
        self.selected_object = primary if primary in self.selected_objects else self.selected_objects[0] if self.selected_objects else -1
        self.update()

    @Slot(int)
    def focus_object(self, index: int) -> None:
        if not 0 <= index < len(self.objects):
            return
        if self.cinematic_camera >= 0:
            self.release_cinematic_camera()
        self.select_object(index)
        self._sample_cinematics()
        special = next((item for item in self.special_instances if item.object_index == index), None)
        if self.show_special_art and special is not None:
            world = special.pose(self.preview_time)
            self.camera.fit_bounds(world.min(axis=0), world.max(axis=0), self.width()/max(self.height(), 1))
            self.update()
            return
        instance = next((item for item in self.display_models if item.object_index == index),None)
        if self.show_models and self.object_library is not None and instance is not None:
            pose = instance_pose(self.object_library,instance,self.preview_time,self.preview_clip)
            transform = instance.transform
            world = pose@transform[:3,:3].T+transform[:3,3]
            self.camera.fit_bounds(world.min(axis=0),world.max(axis=0),self.width()/max(self.height(),1))
            self.update()
            return
        center = np.asarray(self.objects[index].position, dtype=np.float32)
        extent = np.full(3, self.marker_radius*3.0, np.float32)
        self.camera.fit_bounds(center-extent, center+extent, self.width()/max(self.height(),1))
        self.update()

    def pick_object(self, x: float, y: float) -> int:
        self._sample_cinematics()
        matrix = self.camera.projection_matrix(self.width()/max(self.height(),1)) @ self.camera.view_matrix()
        origin, direction = screen_ray(x,y,self.width(),self.height(),matrix)
        hits: list[tuple[float,int]] = []
        marker_indices = set(self.visible_objects if self.show_objects else ())
        if self.show_cinematic_paths:
            marker_indices.update(index for timeline in self.cinematics for index in timeline.track.indices)
        for index in marker_indices:
            center = np.asarray(self.objects[index].position,np.float32)
            clip = matrix @ np.array([*center,1.0],np.float32)
            if clip[3] <= 0 or abs(float(clip[2])) > clip[3]:
                continue
            distance = ray_sphere_distance(origin,direction,center,self.marker_radius*1.2)
            if distance is not None:
                hits.append((distance,index))
        if self.show_sprites:
            view = self.camera.view_matrix()
            for sprite in self.display_sprites:
                if sprite.object_index in self.cinematic_poses and not self.cinematic_poses[sprite.object_index].visible:
                    continue
                sprite = replace(sprite,tiles=sprite.tiles_at(self.preview_time))
                clip = matrix @ np.array([*sprite.position,1.0],np.float32)
                if clip[3] <= 0 or abs(float(clip[2])) > clip[3]:
                    continue
                distance = ray_sprite_distance(origin, direction, sprite, view, camera_position=self.camera.position,
                                              upright_sceneries=self.camera.view == 'Perspective')
                if distance is not None:
                    hits.append((distance,sprite.object_index))
        if self.show_models and self.object_library is not None:
            for instance in self.display_models:
                if not instance.visible:
                    continue
                pose = instance_pose(self.object_library,instance,self.preview_time,
                    self.preview_clip if instance.object_index == self.selected_object else -1)
                transform = instance.transform
                vertices = pose@transform[:3,:3].T+transform[:3,3]
                distance = ray_model_distance(origin,direction,vertices,self.object_library.model(instance.model_id).mesh.indices)
                if distance is not None:
                    hits.append((distance,instance.object_index))
        if self.show_special_art:
            for item in self.special_instances:
                if item.alpha <= .1:
                    continue
                distance = ray_model_distance(origin, direction, item.pose(self.preview_time), item.indices)
                if distance is not None:
                    hits.append((distance, item.object_index))
        return min(hits)[1] if hits else -1

    def set_special_instances(self, instances: tuple[SpecialInstance, ...]) -> None:
        self.special_instances = instances
        self._special_dirty = True
        self.update()

    def set_special_visible(self, enabled: bool) -> None:
        self.show_special_art = enabled
        self.update()

    def set_environment(self, header: LevelHeader | None, library: ObjectLibrary | None,
                        sky: ObjectDefinition | None, water: WaterPreview | None, flash: Texture | None,
                        rates: ScrollRates) -> None:
        self.environment_header, self.environment_library, self.environment_sky = header, library, sky
        self.environment_water, self.environment_flash, self.environment_rates = water, flash, rates
        self._environment_dirty = True
        self.update()

    def set_model_instances(self, library: ObjectLibrary | None, instances: tuple[ModelInstance,...]) -> None:
        resources = {instance.model_id for instance in instances}
        old = {instance.model_id for instance in self.model_instances}
        self._object_mesh_dirty |= library is not self.object_library or resources != old
        self.object_library = library
        self.model_instances = instances
        self.update()

    @Slot(bool)
    def set_models_visible(self, enabled: bool) -> None:
        self.show_models = enabled
        self.update()

    @Slot(float)
    def set_preview_time(self, seconds: float) -> None:
        self.preview_time = max(0.0,min(float(seconds),self.preview_duration))
        self._sample_cinematics()
        self.preview_time_changed.emit(self.preview_time)
        self.update()

    def set_cinematics(self, timelines: tuple[CinematicTimeline, ...]) -> None:
        self.release_cinematic_camera()
        self.cinematics = timelines
        self._cinematic_sample_key = None
        self._cinematic_paths = tuple(RacePath(t.track.label, 'camera' if t.track.camera else 'cinematic',
            0, False, path_points(t.track), tuple(n.key for n in t.track.nodes), t.track.loop >= 0) for t in timelines)
        self._cinematic_dirty = True
        self._sample_cinematics()
        self.update()

    def release_cinematic_camera(self) -> None:
        if self._saved_cinematic_camera is not None:
            self.camera = self._saved_cinematic_camera
        self._saved_cinematic_camera = None
        self.cinematic_camera = -1
        self.cinematic_camera_released.emit()

    def set_cinematic_camera(self, owner: int) -> None:
        if owner < 0:
            self.release_cinematic_camera()
        elif any(t.track.owner == owner and t.track.camera for t in self.cinematics):
            if self._saved_cinematic_camera is None:
                self._release_input()
                self._saved_cinematic_camera = copy.deepcopy(self.camera)
                self.camera = copy.deepcopy(self.camera)
            self.cinematic_camera = owner
            self._cinematic_sample_key = None
            self._sample_cinematics()
        self.update()

    def _sample_cinematics(self) -> None:
        key = (self.preview_time, self.cinematic_motion, id(self.model_instances), id(self.sprites), self.cinematic_camera)
        if self._cinematic_sample_key == key:
            return
        self._cinematic_sample_key = key
        seconds = self.preview_time if self.cinematic_motion else 0.
        poses = {t.track.owner: t.sample(seconds) for t in self.cinematics}
        actors = {t.track.actor: poses[t.track.owner] for t in self.cinematics}
        for timeline in self.cinematics:
            node = timeline.track.nodes[0]
            target = actors.get(int(node.value('nextAnim', -1)))
            if node.value('rotateType', 0) == 3 and target is not None:
                poses[timeline.track.owner] = look_at(poses[timeline.track.owner], target)
        self.cinematic_poses = poses
        self.display_models = tuple(replace(instance, position=poses[instance.object_index].position,
            angles=poses[instance.object_index].angles, scale=instance.definition.scale*poses[instance.object_index].scale,
            clip_index=poses[instance.object_index].clip, sampled_frame=poses[instance.object_index].frame,
            visible=poses[instance.object_index].visible) if instance.object_index in poses else instance for instance in self.model_instances)
        old_sprites = self.display_sprites
        self.display_sprites = tuple(replace(sprite, position=poses[sprite.object_index].position,
            scale=next(t.track.target.scale for t in self.cinematics if t.track.owner == sprite.object_index and t.track.target)*poses[sprite.object_index].scale)
            if sprite.object_index in poses else sprite for sprite in self.sprites)
        # SpriteTile/TextureFrame contain NumPy pixel arrays. Dataclass equality
        # is ambiguous after artwork caches are rebuilt. Compare transform
        # values and resource owners without comparing pixel arrays here.
        if len(self.display_sprites)!=len(old_sprites) or any(
                (a.object_index,a.sprite_id,a.position,a.scale,a.frame_speed,a.initial_frame,a.upright) !=
                (b.object_index,b.sprite_id,b.position,b.scale,b.frame_speed,b.initial_frame,b.upright)
                or a.tiles is not b.tiles or a.frames is not b.frames
                for a,b in zip(self.display_sprites,old_sprites)):
            self._sprites_dirty = True
        if self.cinematic_camera in poses:
            pose = poses[self.cinematic_camera]
            self.camera.view = 'Perspective'
            self.camera.near, self.camera.far = 10., 15000.
            self.camera.position = np.asarray(pose.position, np.float32)
            self.camera.yaw = -90-math.degrees(pose.angles[0])
            self.camera.pitch = math.degrees(pose.angles[1])
            self.camera.view_override = camera_view(pose)

    @Slot(bool)
    def set_vertex_colors(self, enabled: bool) -> None:
        self.vertex_colors = enabled
        self.update()

    @Slot(bool)
    def set_wireframe(self, enabled: bool) -> None:
        self.wireframe = enabled
        self.update()

    @Slot(bool)
    def set_segment_bounds_visible(self, enabled: bool) -> None:
        self.show_segment_bounds = enabled
        self.update()

    @Slot(bool)
    def set_backface_culling(self, enabled: bool) -> None:
        self.cull_backfaces = enabled
        self.update()

    @Slot(int)
    def set_selected_segment(self, index: int) -> None:
        if self.model is None or not -1 <= index < len(self.model.segments):
            index = -1
        self.selected_segment = index
        if self.isolate_segment:
            self.reset_camera()
        self.update()

    @Slot(bool)
    def set_segment_isolated(self, enabled: bool) -> None:
        self.isolate_segment = enabled and self.selected_segment >= 0
        self.reset_camera()

    def set_catalog_caption(self, level_name: str, geometry_id: int) -> None:
        summary = "Track geometry unavailable"
        if self.model is not None:
            summary = (f"{len(self.model.segments)} segments · {self.model.vertex_count:,} vertices · "
                       f"{self.model.triangle_count:,} triangles · {len(self.textures)} textures")
        self.hud.setText(
            f"{level_name} · Geometry {geometry_id}\n{summary}\n"
            "RMB look · MMB pan · WASD fly · Q/E vertical · Shift boost\n"
            "Alt + RMB orbit · Wheel zoom · F fit · Esc release"
        )
        self.hud.adjustSize()

    @Slot(bool)
    def set_grid_visible(self, visible: bool) -> None:
        self.show_grid = visible
        self._grid_preference = visible
        self.grid_label.setVisible(visible)
        self.grid_changed.emit(visible)
        self.update()

    @Slot(bool)
    def set_axes_visible(self, visible: bool) -> None:
        self.show_axes = visible
        self.orientation.setVisible(visible)
        self.update()

    @Slot()
    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._last_tick, 0.1)
        self._last_tick = now
        if self._panning and QWidget.mouseGrabber() is not self:
            self._finish_pan()
        if not self.isVisible():
            return
        if self.preview_playing:
            self.set_preview_time((self.preview_time+dt*self.preview_rate) % self.preview_duration)
        if self.hasFocus() and self._drag is None and not self._panning and self.cinematic_camera < 0:
            self.camera.move(
                float((Qt.Key.Key_W in self._keys) - (Qt.Key.Key_S in self._keys)),
                float((Qt.Key.Key_D in self._keys) - (Qt.Key.Key_A in self._keys)),
                float((Qt.Key.Key_E in self._keys) - (Qt.Key.Key_Q in self._keys)),
                dt, Qt.Key.Key_Shift in self._keys,
            )
        self.update()
        if now - self._last_report >= 1.0:
            fps = (self.frame_count - self._frames_at_report) / (now - self._last_report)
            self._frames_at_report = self.frame_count
            self._last_report = now
            x, y, z = self.camera.position
            self.status_changed.emit(
                f"{fps:.0f} FPS | XYZ {x:.1f}, {y:.1f}, {z:.1f} | FOV {self.camera.fov:.0f}°"
            )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._panning:
            if event.key() == Qt.Key.Key_Escape:
                self._release_input()
            event.accept()
            return
        if self.cinematic_camera >= 0 and event.key() == Qt.Key.Key_Escape:
            self.release_cinematic_camera()
            event.accept()
            return
        if self._drag is not None:
            if event.key() == Qt.Key.Key_Escape or (event.key() == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.finish_object_drag(cancel=True)
            event.accept()
            return
        arrows = {Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1),
                  Qt.Key.Key_Up: (2, -1), Qt.Key.Key_Down: (2, 1),
                  Qt.Key.Key_PageUp: (1, 1), Qt.Key.Key_PageDown: (1, -1)}
        if not self.grid_pick and not self.material_active and self.object_move_mode and event.key() in arrows and self.selected_object >= 0:
            axis, sign = arrows[event.key()]
            boost = 4 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self.object_nudged.emit(self.selected_object, axis, sign * self.object_move_step * boost)
            event.accept()
        elif event.key() in MOVEMENT_KEYS:
            self._keys.add(event.key())
            event.accept()
        elif event.key() == Qt.Key.Key_F:
            self.reset_camera()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self._release_input()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() in MOVEMENT_KEYS:
            if not event.isAutoRepeat():
                self._keys.discard(event.key())
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def _press_geometry(self, event: QMouseEvent) -> None:
        if self.model is None:
            return
        x, y = event.position().x(), event.position().y()
        matrix = self.camera.projection_matrix(self.width()/max(self.height(), 1)) @ self.camera.view_matrix()
        handle = self.translation_handle_at(x, y)
        if handle is not None and self.geometry_center is not None:
            self._drag = TranslationDrag.begin(self.geometry_center, handle if handle >= 0 else None,
                                               x, y, self.camera.forward, matrix, self.width(), self.height())
            if self._drag is not None:
                self._drag_is_geometry = True
                self._drag_press = event.position().toPoint()
                self._drag_moved = False
                self._keys.clear()
                self.geometry_drag_started.emit()
                if self._drag is not None:
                    self.grabMouse()
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if not self.geometry_faces:
            hit = pick_track_vertex(self.model,x,y,self.width(),self.height(),matrix,
                segment=self.selected_segment if self.isolate_segment else -1,cull_backfaces=self.cull_backfaces)
            if hit is not None:
                self.geometry_picked.emit(*hit,bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))
            return
        origin, direction = screen_ray(x, y, self.width(), self.height(), matrix)
        hit = pick_track_face(self.model, origin, direction,
            segment=self.selected_segment if self.isolate_segment else -1, cull_backfaces=self.cull_backfaces)
        if hit is None:
            return
        segment, face = hit
        self.geometry_picked.emit(segment, face, bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.cinematic_camera >= 0 and event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self.release_cinematic_camera()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.button() == Qt.MouseButton.LeftButton:
            if self._looking or self._panning or self._drag is not None:
                event.accept()
                return
            self.prepare_pointer_selection.emit()
            x, y = event.position().x(), event.position().y()
            if self.grid_pick:
                matrix = self.camera.projection_matrix(self.width()/max(self.height(), 1)) @ self.camera.view_matrix()
                origin, direction = screen_ray(x, y, self.width(), self.height(), matrix)
                terrain = self._grid_terrain()
                hit = terrain.raycast(origin, direction) if terrain else None
                if hit is not None:
                    self.grid_origin = np.asarray(hit, np.float32)
                    self.set_grid_follow_selection(False)
                    self.set_grid_visible(True)
                    self.grid_pick = False
                    self.unsetCursor()
                event.accept()
                return
            if self.surface_picker is not None:
                matrix=self.camera.projection_matrix(self.width()/max(self.height(),1)) @ self.camera.view_matrix()
                origin,direction=screen_ray(x,y,self.width(),self.height(),matrix)
                hit=self.surface_picker.raycast(origin,direction)
                if hit is not None:self.surface_picked.emit(tuple(float(v) for v in hit))
                event.accept()
                return
            if self.geometry_active:
                if self.geometry_picking and self.model is not None:
                    self._press_geometry(event)
                event.accept()
                return
            if self.material_picking and self.model is not None:
                matrix = self.camera.projection_matrix(self.width() / max(self.height(), 1)) @ self.camera.view_matrix()
                origin, direction = screen_ray(x, y, self.width(), self.height(), matrix)
                picked = pick_track_face(self.model, origin, direction,
                    segment=self.selected_segment if self.isolate_segment and self.material_isolation is None else -1,
                    cull_backfaces=self.cull_backfaces, batch=self.material_isolation)
                if picked is not None:
                    self.track_face_picked.emit(*picked)
                event.accept()
                return
            if self.route_pick_slot is not None:
                self.route_target_picked.emit(self.pick_object(x, y))
                event.accept()
                return
            lane = self.lane_at(x, y)
            if lane is not None:
                self.route_lane = lane
                self.route_lane_selected.emit(lane)
            handle = self.translation_handle_at(x, y)
            if self.route_lane >= 0 and lane is not None:
                handle = -1
            if self.route_lane < 0 and event.modifiers() & Qt.KeyboardModifier.ControlModifier and (handle is None or handle == -1):
                picked = self.pick_object(x, y)
                selected_indices = list(self.selected_objects)
                if picked >= 0:
                    if picked in selected_indices:
                        selected_indices.remove(picked)
                    else:
                        selected_indices.append(picked)
                self.set_selection(tuple(selected_indices), picked)
                self.object_selected.emit(self.selected_object)
                event.accept()
                return
            if handle is None:
                selected = self.pick_object(x, y)
                if selected not in self.selected_objects:
                    self.set_selection((selected,), selected)
                else:
                    self.select_object(selected)
                self.object_selected.emit(selected)
            else:
                selected = self.selected_object
            if (self.mouse_move_enabled or self.route_lane >= 0) and selected >= 0:
                if self.transform_mode != "Move" and self.route_lane < 0 and handle is None:
                    event.accept()
                    return
                matrix = self.camera.projection_matrix(self.width()/max(self.height(), 1)) @ self.camera.view_matrix()
                center = self.handle_center()
                if self.transform_mode == "Move" or self.route_lane >= 0:
                    self._drag = TranslationDrag.begin(center, handle if handle is not None and handle >= 0 else None,
                                                       x, y, self.camera.forward, matrix, self.width(), self.height())
                else:
                    self._drag = ScalarDrag.begin(self.transform_mode, handle if handle is not None and handle >= 0 else None,
                                                  center, x, y, matrix, self.width(), self.height())
                if self._drag is not None:
                    self._keys.clear()
                    self._drag_press = event.position().toPoint()
                    self._drag_moved = False
                    self.object_drag_started.emit(selected)
                    if self._drag is not None:
                        self.grabMouse()
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            if not self._looking and not self._panning and self._drag is None:
                self._panning = True
                self._pan_position = event.position()
                self._hover_handle = None
                self._keys.clear()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.grabMouse()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            if self._drag is not None or self._panning or self._looking:
                event.accept()
                return
            self._looking = True
            self._orbiting = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            self._cursor_before_look = QCursor.pos()
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.grabMouse()
            QCursor.setPos(self.mapToGlobal(self.rect().center()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is not None:
            self._preview_drag(event)
            event.accept()
        elif self._panning:
            if event.buttons() & Qt.MouseButton.MiddleButton:
                delta = event.position()-self._pan_position
                self._pan_position = event.position()
                self.camera.pan(delta.x(), delta.y(), max(self.height(), 1))
                self.update()
            else:
                self._finish_pan()
            event.accept()
        elif self._looking:
            center = self.mapToGlobal(self.rect().center())
            delta = event.globalPosition().toPoint() - center
            if not delta.isNull():
                self.camera.look(float(delta.x()), float(delta.y()), orbit=self._orbiting)
                QCursor.setPos(center)
                self.update()
            event.accept()
        else:
            hovered = self.translation_handle_at(event.position().x(), event.position().y())
            if hovered != self._hover_handle:
                self._hover_handle = hovered
                self.setCursor(Qt.CursorShape.OpenHandCursor) if hovered is not None else self.unsetCursor()
            super().mouseMoveEvent(event)

    def _preview_drag(self, event: QMouseEvent) -> None:
        if self._drag is None:
            return
        if not self._drag_moved and (event.position().toPoint()-self._drag_press).manhattanLength() < 3:
            return
        self._drag_moved = True
        snap = self.grid_snap or bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if isinstance(self._drag, ScalarDrag):
            value = self._drag.value_at(event.position().x(), event.position().y(), snap)
            if value is not None:
                self.transform_drag_preview.emit(self.transform_mode, self._drag.axis if self._drag.axis is not None else -1, value)
            return
        step = self.object_move_step if snap else 1
        if self._drag_is_geometry:
            position = self._drag.position_at(event.position().x(), event.position().y(), self.geometry_step if snap else 1)
            if position is not None:
                self.geometry_drag_preview.emit(position)
            return
        position = (self._drag.world_at(event.position().x(), event.position().y(), step if snap else 0)
                    if self.route_lane >= 0 else self._drag.position_at(event.position().x(), event.position().y(), step))
        if position is not None:
            self.object_drag_preview.emit(position)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self._preview_drag(event)
            self.finish_object_drag()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton and self._drag is not None:
            event.accept()
        elif event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._finish_pan()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton and self._looking:
            self._release_input()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _finish_pan(self) -> None:
        if self._panning:
            self._panning = False
            self._keys.clear()
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
            self.unsetCursor()

    def _release_input(self) -> None:
        if self.grid_pick:
            self.grid_pick = False
            self.unsetCursor()
        self.finish_object_drag(cancel=True)
        self.route_pick_slot = None
        self._keys.clear()
        self._finish_pan()
        if self._looking:
            self._looking = False
            self._orbiting = False
            self.releaseMouse()
            self.unsetCursor()
            QCursor.setPos(self._cursor_before_look)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._release_input()
        super().focusOutEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._release_input()
        super().hideEvent(event)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and hasattr(self, "_keys"):
            self._release_input()
        elif event.type() == QEvent.Type.UngrabMouse and getattr(self, '_panning', False):
            self._finish_pan()
        return super().event(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._drag is not None:
            event.accept()
            return
        self.camera.zoom(event.angleDelta().y() / 120.0)
        self.update()
        event.accept()
