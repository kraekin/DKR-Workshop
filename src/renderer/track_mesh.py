"""Core-profile track buffers, per-triangle culling and segment bounds."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from functools import partial

import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader

from src.core.level_model import BACKFACE_DRAW, Bounds, FloatArray, IndexArray, LevelModel
from src.core.textures import Texture, TextureFormat, SpriteInstance, model_uvs
from src.core.environment import texture_frame, scroll_delta, ScrollRates
from src.renderer.shaders import TRACK_FRAGMENT_SHADER, TRACK_VERTEX_SHADER, SPRITE_VERTEX_SHADER, SPRITE_FRAGMENT_SHADER
from src.renderer.transparency import TransparentDraw
from src.renderer.camera import billboard_axes


@dataclass(frozen=True)
class DrawRange:
    segment_index: int
    first_index: int
    index_count: int
    double_sided: bool
    texture_key: tuple[int, int] | None
    translucent: bool
    vertex_alpha: bool
    decal: bool
    center: FloatArray
    batch_index: int = 0


def bounds_lines(bounds: Bounds) -> FloatArray:
    """Twelve box edges, each with two XYZ endpoints."""
    corners = np.array([
        [x, y, z] for x in (bounds.minimum[0], bounds.maximum[0])
        for y in (bounds.minimum[1], bounds.maximum[1])
        for z in (bounds.minimum[2], bounds.maximum[2])
    ], dtype=np.float32)
    return np.ascontiguousarray(np.array([
        endpoint for index in range(8) for bit in (1, 2, 4) if not index & bit
        for endpoint in (corners[index], corners[index | bit])
    ], dtype=np.float32))


class TrackMesh:
    """Construct/delete only while the owning viewport's context is current."""

    def __init__(self, model: LevelModel, textures: Mapping[int, Texture] | None = None) -> None:
        self.vao = self.vbo = self.ebo = self.bounds_vao = self.bounds_vbo = self.program = 0
        self.selection_vao = self.selection_ebo = 0
        self.model = model
        self.textures = textures or {}
        self.motion_enabled = False
        self.seconds = 0.
        self.omitted_batches: set[tuple[int, int]] = set()
        self._environment_key: object = None
        self._selection_key: object = None
        self._selection_lines = self._selection_points = 0
        self.ranges: list[DrawRange] = []
        self.segment_count = len(model.segments)
        self.visible_triangle_count = 0
        self.draw_call_count = 0
        self.texture_handles: dict[tuple[int, int], int] = {}
        textures = textures or {}
        try:
            self.program = int(compileProgram(
                compileShader(TRACK_VERTEX_SHADER, GL.GL_VERTEX_SHADER),
                compileShader(TRACK_FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER),
            ))
            self.matrix_uniform = int(GL.glGetUniformLocation(self.program, "u_view_projection"))
            self.colors_uniform = int(GL.glGetUniformLocation(self.program, "u_vertex_colors"))
            self.wire_uniform = int(GL.glGetUniformLocation(self.program, "u_wireframe"))
            self.texture_uniform = int(GL.glGetUniformLocation(self.program, "u_textured"))
            self.alpha_uniform = int(GL.glGetUniformLocation(self.program, "u_vertex_alpha"))
            GL.glUseProgram(self.program)
            GL.glUniform1i(GL.glGetUniformLocation(self.program, "u_texture"), 0)
            GL.glUseProgram(0)
            # Per-corner vertices preserve UV seams without changing core XYZ indices.
            corners = model.flat_vertices[model.indices].reshape(-1, 7)
            uv = model_uvs(model, textures).reshape(-1, 2) if textures else np.zeros((len(corners), 2), np.float32)
            vertices = np.ascontiguousarray(np.column_stack((corners, uv)), dtype=np.float32)
            indices: list[IndexArray] = []
            cursor = 0
            for segment in model.segments:
                batches = (*segment.batches, segment.terminal_batch)
                for batch_index, (batch, following) in enumerate(zip(batches, batches[1:])):
                    if batch.hidden:
                        continue
                    first, end = batch.faces_offset, following.faces_offset
                    faces = np.arange((segment.face_base + first) * 3,
                                      (segment.face_base + end) * 3, dtype=np.uint32).reshape(-1, 3)
                    flags = segment.triangle_flags[first:end]
                    key = None
                    translucent = False
                    raw_colors = segment.colors[batch.vertices_offset:following.vertices_offset]
                    vertex_alpha = bool(batch.flags & (1 << 27)) or bool(np.any(
                        (raw_colors[:, 0] == 1) & (raw_colors[:, 1] == 1)))
                    if batch.texture_index != 255 and textures:
                        texture_id = model.textures[batch.texture_index].texture_id
                        texture = textures[texture_id]
                        key = (texture_id, texture.frame_index(batch.texture_offset))
                        frame = texture.frames[key[1]]
                        header = frame.header
                        translucent = header.render_mode in (0, 2) or header.format in (
                            TextureFormat.IA4, TextureFormat.IA8, TextureFormat.IA16)
                        for frame_index, upload_frame in enumerate(texture.frames):
                            upload_key = texture_id, frame_index
                            if upload_key in self.texture_handles:
                                continue
                            handle = int(GL.glGenTextures(1))
                            self.texture_handles[upload_key] = handle
                            GL.glBindTexture(GL.GL_TEXTURE_2D, handle)
                            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
                            upload_header = upload_frame.header
                            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, upload_header.width, upload_header.height,
                                            0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, upload_frame.pixels)
                            for axis, clamp in ((GL.GL_TEXTURE_WRAP_S, upload_header.clamp_u),
                                                (GL.GL_TEXTURE_WRAP_T, upload_header.clamp_v)):
                                GL.glTexParameteri(GL.GL_TEXTURE_2D, axis, GL.GL_CLAMP_TO_EDGE if clamp else GL.GL_REPEAT)
                            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                    translucent |= vertex_alpha or bool(batch.flags & (4 | 0x2000))
                    for double_sided in (False, True):
                        selected = faces[((flags & BACKFACE_DRAW) != 0) == double_sided]
                        count = selected.size
                        if count:
                            indices.append(selected.reshape(-1))
                            center = corners[selected.reshape(-1), :3].mean(axis=0)
                            self.ranges.append(DrawRange(segment.index, cursor, count, double_sided,
                                                         key, translucent, vertex_alpha, bool(batch.flags & 0x800), center, batch_index))
                            cursor += count
            elements = np.concatenate(indices).astype(np.uint32) if indices else np.empty(0, dtype=np.uint32)
            self._elements = elements
            self.visible_triangle_count = len(elements) // 3
            self._base_buffer = vertices.copy()
            self.vao = int(GL.glGenVertexArrays(1))
            self.vbo = int(GL.glGenBuffers(1))
            self.ebo = int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self.vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_STATIC_DRAW)
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self.ebo)
            GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, elements.nbytes, elements, GL.GL_STATIC_DRAW)
            for location, count, offset in ((0, 3, 0), (1, 4, 12), (2, 2, 28)):
                GL.glEnableVertexAttribArray(location)
                GL.glVertexAttribPointer(location, count, GL.GL_FLOAT, GL.GL_FALSE, 36, ctypes.c_void_p(offset))
            boxes = np.concatenate([bounds_lines(segment.bounds) for segment in model.segments])
            self.bounds_vao = int(GL.glGenVertexArrays(1))
            self.bounds_vbo = int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self.bounds_vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.bounds_vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, boxes.nbytes, boxes, GL.GL_STATIC_DRAW)
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, 12, ctypes.c_void_p(0))
            GL.glDisableVertexAttribArray(1)
            self.selection_vao = int(GL.glGenVertexArrays(1))
            self.selection_ebo = int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self.selection_vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
            GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, 36, ctypes.c_void_p(0))
            GL.glEnableVertexAttribArray(0)
            GL.glDisableVertexAttribArray(1)
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self.selection_ebo)
            GL.glBindVertexArray(0)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 4)
        except Exception:
            self.delete()
            raise

    def update_environment(self, seconds: float, motion: bool, rates: ScrollRates,
                           omitted: set[tuple[int, int]]) -> None:
        self.seconds, self.motion_enabled, self.omitted_batches = seconds, motion, omitted
        tick = max(0, int(seconds*60)) if motion else 0
        key = tick if rates else 0, tuple(sorted(rates.items()))
        if key == self._environment_key:
            return
        buffer = self._base_buffer.copy()
        if tick:
            for segment in self.model.segments:
                for batch, following in zip(segment.batches, (*segment.batches[1:], segment.terminal_batch)):
                    if batch.texture_index not in rates or batch.texture_index == 255:
                        continue
                    texture_id = self.model.textures[batch.texture_index].texture_id
                    h = self.textures[texture_id].frames[0].header
                    rate = rates[batch.texture_index]
                    delta = scroll_delta(rate, tick)/(32*np.array((h.width, h.height)))
                    last = delta-scroll_delta(rate, tick-1)/(32*np.array((h.width, h.height)))
                    start, end = (segment.face_base+batch.faces_offset)*3, (segment.face_base+following.faces_offset)*3
                    uv = buffer[start:end, 7:9].reshape(-1, 3, 2)
                    moving = (segment.triangle_flags[batch.faces_offset:following.faces_offset] & 0x80) == 0
                    shifted = uv[moving]+delta
                    # Source wraps all corners together by eight texture widths,
                    # based on uv0, before applying the final tick's increment.
                    shifted -= np.floor((shifted[:, :1]-last)/8)*8
                    uv[moving] = shifted
        if rates or self._environment_key is not None:
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, buffer.nbytes, buffer)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self._environment_key = key

    def update_geometry(self, model: LevelModel) -> None:
        """Retain textures/shaders/index buffers during fixed-topology XYZ preview."""
        if model.indices.shape != self.model.indices.shape or not np.array_equal(model.indices, self.model.indices):
            raise ValueError('Geometry preview requires unchanged track topology')
        self.model = model
        self._base_buffer[:, :3] = model.flat_vertices[model.indices].reshape(-1, 7)[:, :3]
        for group in self.ranges:
            group.center[:] = self._base_buffer[self._elements[group.first_index:group.first_index+group.index_count], :3].mean(axis=0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, self._base_buffer.nbytes, self._base_buffer)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self._environment_key = None

    def draw(self, matrix: FloatArray, *, vertex_colors: bool, wireframe: bool,
             cull_backfaces: bool, isolated_segment: int, textured: bool = False,
             camera_position: FloatArray | None = None, transparent_pass: bool | None = None,
             ranges: Sequence[DrawRange] | None = None) -> None:
        candidates = self.ranges if ranges is None else ranges
        if transparent_pass is not True:
            self.draw_call_count = 0
        if transparent_pass is not None and not any(
                (isolated_segment == -1 or group.segment_index == isolated_segment)
                and (group.segment_index, group.batch_index) not in self.omitted_batches
                and bool(textured and group.translucent) == transparent_pass for group in candidates):
            return
        GL.glUseProgram(self.program)
        GL.glUniformMatrix4fv(self.matrix_uniform, 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
        GL.glUniform1i(self.colors_uniform, int(vertex_colors))
        GL.glBindVertexArray(self.vao)
        GL.glFrontFace(GL.GL_CCW)
        GL.glCullFace(GL.GL_BACK)
        try:
            if wireframe:
                GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glPolygonOffset(1.0, 1.0)
            GL.glUniform1i(self.wire_uniform, 0)
            self._draw_ranges(cull_backfaces, isolated_segment, textured, camera_position, transparent_pass, ranges)
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
            if wireframe and transparent_pass is not True:
                GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE)
                GL.glDepthFunc(GL.GL_LEQUAL)
                GL.glUniform1i(self.wire_uniform, 1)
                self._draw_ranges(cull_backfaces, isolated_segment, False, camera_position, ranges=ranges)
        finally:
            GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
            GL.glDepthFunc(GL.GL_LESS)
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
            GL.glDisable(GL.GL_CULL_FACE)
            GL.glDisable(GL.GL_BLEND)
            GL.glDepthMask(GL.GL_TRUE)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glBindVertexArray(0)
            GL.glUseProgram(0)

    def _draw_ranges(self, cull_backfaces: bool, isolated_segment: int, textured: bool,
                     camera_position: FloatArray | None, transparent_pass: bool | None = None,
                     ranges: Sequence[DrawRange] | None = None) -> None:
        groups = [group for group in (self.ranges if ranges is None else ranges)
                  if isolated_segment == -1 or group.segment_index == isolated_segment]
        if textured and ranges is None:
            position = camera_position if camera_position is not None else np.zeros(3, np.float32)
            groups.sort(key=lambda group: (group.translucent,
                        -float(np.sum((group.center - position) ** 2)) if group.translucent else 0.0))
        # Each draw starts with unknown state. Reuse only state set in this call:
        # hundreds of repeated PyOpenGL state/error checks otherwise dominate
        # cinematic playback even when the GPU is mostly idle.
        previous_cull = previous_alpha = previous_texture = None
        previous_textured = previous_vertex_alpha = None
        GL.glActiveTexture(GL.GL_TEXTURE0)
        for group in groups:
            if (group.segment_index, group.batch_index) in self.omitted_batches:
                continue
            if transparent_pass is not None and bool(textured and group.translucent) != transparent_pass:
                continue
            if isolated_segment != -1 and group.segment_index != isolated_segment:
                continue
            culling = cull_backfaces and not group.double_sided
            if culling != previous_cull:
                (GL.glEnable if culling else GL.glDisable)(GL.GL_CULL_FACE)
                previous_cull = culling
            alpha = textured and group.translucent
            if alpha != previous_alpha:
                if alpha:
                    GL.glEnable(GL.GL_BLEND)
                    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
                else:
                    GL.glDisable(GL.GL_BLEND)
                GL.glDepthMask(GL.GL_FALSE if alpha else GL.GL_TRUE)
                previous_alpha = alpha
            if group.decal:
                GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glPolygonOffset(-1.0, -1.0)
            texture_key = group.texture_key
            if texture_key is not None and self.motion_enabled:
                batch = self.model.segments[group.segment_index].batches[group.batch_index]
                texture_key = texture_key[0], texture_frame(self.textures[texture_key[0]], batch, self.seconds)
            texture = self.texture_handles.get(texture_key, 0)
            if texture != previous_texture:
                GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
                previous_texture = texture
            has_texture = int(textured and group.texture_key is not None)
            if has_texture != previous_textured:
                GL.glUniform1i(self.texture_uniform, has_texture)
                previous_textured = has_texture
            vertex_alpha = int(textured and group.vertex_alpha)
            if vertex_alpha != previous_vertex_alpha:
                GL.glUniform1i(self.alpha_uniform, vertex_alpha)
                previous_vertex_alpha = vertex_alpha
            GL.glDrawElements(GL.GL_TRIANGLES, group.index_count, GL.GL_UNSIGNED_INT,
                              ctypes.c_void_p(group.first_index * 4))
            self.draw_call_count += 1
            if group.decal:
                GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)

    def transparent_draws(self, matrix: FloatArray, *, vertex_colors: bool, wireframe: bool,
                          cull_backfaces: bool, isolated_segment: int, textured: bool,
                          camera_position: FloatArray) -> list[TransparentDraw]:
        return [TransparentDraw(group.center, partial(self.draw, matrix, vertex_colors=vertex_colors,
                    wireframe=wireframe, cull_backfaces=cull_backfaces, isolated_segment=isolated_segment,
                    textured=textured, camera_position=camera_position, transparent_pass=True, ranges=(group,)))
                for group in self.ranges if textured and group.translucent
                and (isolated_segment == -1 or group.segment_index == isolated_segment)
                and (group.segment_index, group.batch_index) not in self.omitted_batches]

    def draw_bounds(self, *, selected_segment: int, isolated_segment: int) -> None:
        """Use the viewport's already-bound line shader and world-space matrix."""
        GL.glBindVertexArray(self.bounds_vao)
        for index in range(self.segment_count):
            if isolated_segment != -1 and index != isolated_segment:
                continue
            color = (1.0, 0.76, 0.25) if index == selected_segment else (0.25, 0.62, 0.95)
            GL.glVertexAttrib3f(1, *color)
            GL.glDrawArrays(GL.GL_LINES, index * 24, 24)
        GL.glBindVertexArray(0)

    def draw_geometry_points(self, matrix: FloatArray, uniform: int, segment: int) -> None:
        if not 0 <= segment < len(self.model.segments):
            return
        s = self.model.segments[segment]
        GL.glBindVertexArray(self.selection_vao)
        GL.glUniformMatrix4fv(uniform, 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
        GL.glVertexAttrib3f(1, .25, .85, 1.)
        GL.glDepthFunc(GL.GL_LEQUAL)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glPointSize(4.)
        try:
            for batch, end in zip(s.batches, (*s.batches[1:], s.terminal_batch)):
                if not batch.hidden:
                    GL.glDrawArrays(GL.GL_POINTS, (s.face_base+batch.faces_offset)*3, (end.faces_offset-batch.faces_offset)*3)
        finally:
            GL.glPointSize(1.)
            GL.glDepthMask(GL.GL_TRUE)
            GL.glDepthFunc(GL.GL_LESS)
            GL.glBindVertexArray(0)

    def draw_selection(self, matrix: FloatArray, uniform: int, faces: tuple[tuple[int, int], ...],
                       vertices: tuple[tuple[int, int], ...]) -> None:
        key = faces, vertices
        GL.glBindVertexArray(self.selection_vao)
        if self._selection_key != key:
            line_indices: list[int] = []
            point_indices: list[int] = []
            for segment, face in faces:
                if 0 <= segment < len(self.model.segments) and 0 <= face < self.model.segments[segment].triangle_count:
                    first = (self.model.segments[segment].face_base + face) * 3
                    line_indices.extend((first, first + 1, first + 1, first + 2, first + 2, first))
            for segment, vertex in vertices:
                if 0 <= segment < len(self.model.segments):
                    s = self.model.segments[segment]
                    matches = np.flatnonzero(s.indices.reshape(-1) == vertex)
                    if len(matches):
                        point_indices.append(s.face_base * 3 + int(matches[0]))
            data = np.asarray(line_indices + point_indices, np.uint32)
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self.selection_ebo)
            GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, data.nbytes, data, GL.GL_DYNAMIC_DRAW)
            self._selection_lines, self._selection_points = len(line_indices), len(point_indices)
            self._selection_key = key
        GL.glUniformMatrix4fv(uniform, 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
        GL.glDisable(GL.GL_DEPTH_TEST)
        try:
            GL.glVertexAttrib3f(1, 1., .78, .1)
            GL.glDrawElements(GL.GL_LINES, self._selection_lines, GL.GL_UNSIGNED_INT, ctypes.c_void_p(0))
            GL.glVertexAttrib3f(1, .2, 1., 1.)
            GL.glPointSize(7.)
            GL.glDrawElements(GL.GL_POINTS, self._selection_points, GL.GL_UNSIGNED_INT, ctypes.c_void_p(self._selection_lines * 4))
        finally:
            GL.glPointSize(1.)
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glBindVertexArray(0)

    def delete(self) -> None:
        if self.texture_handles:
            GL.glDeleteTextures(list(self.texture_handles.values()))
            self.texture_handles.clear()
        for name in ("vbo", "ebo", "bounds_vbo", "selection_ebo"):
            resource = getattr(self, name)
            if resource:
                GL.glDeleteBuffers(1, [resource])
                setattr(self, name, 0)
        for name in ("vao", "bounds_vao", "selection_vao"):
            resource = getattr(self, name)
            if resource:
                GL.glDeleteVertexArrays(1, [resource])
                setattr(self, name, 0)
        if self.program:
            GL.glDeleteProgram(self.program)
            self.program = 0

@dataclass(frozen=True)
class SpriteDrawRange:
    texture_id: int
    first: int
    count: int
    translucent: bool
    center: FloatArray
    object_index: int = -1
    animation_frame: int = -1
    upright: bool = False


class SpriteMesh:
    """Camera-facing multi-tile scenery, with opaque cutouts and blended effects."""
    def __init__(self, instances: tuple[SpriteInstance,...]) -> None:
        self.vao=self.vbo=self.program=0
        self.textures: dict[int,int]={}
        self.ranges: list[SpriteDrawRange]=[]
        self.instance_count=len(instances)
        self.instances=instances
        self.draw_call_count=0
        try:
            self.program=int(compileProgram(compileShader(SPRITE_VERTEX_SHADER,GL.GL_VERTEX_SHADER),
                                            compileShader(SPRITE_FRAGMENT_SHADER,GL.GL_FRAGMENT_SHADER)))
            self.matrix_uniform=GL.glGetUniformLocation(self.program,'u_view_projection')
            self.right_uniform=GL.glGetUniformLocation(self.program,'u_camera_right')
            self.up_uniform=GL.glGetUniformLocation(self.program,'u_camera_up')
            self.position_uniform=GL.glGetUniformLocation(self.program,'u_camera_position')
            self.upright_uniform=GL.glGetUniformLocation(self.program,'u_upright')
            GL.glUseProgram(self.program);GL.glUniform1i(GL.glGetUniformLocation(self.program,'u_texture'),0);GL.glUseProgram(0)
            opaque: dict[tuple[int,int,int,bool],list[tuple[int,FloatArray]]]={}
            translucent: list[tuple[int,FloatArray,FloatArray,int,int,bool]]=[]
            for instance in instances:
                center=np.array(instance.position,np.float32)
                all_tiles = [(frame,tile) for frame,tiles in enumerate(instance.frames) for tile in tiles] if instance.frames else [(-1,tile) for tile in instance.tiles]
                for frame_index,tile in all_tiles:
                    header=tile.frame.header
                    if tile.texture_id not in self.textures:
                        handle=int(GL.glGenTextures(1));self.textures[tile.texture_id]=handle
                        GL.glBindTexture(GL.GL_TEXTURE_2D,handle);GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT,1)
                        GL.glTexImage2D(GL.GL_TEXTURE_2D,0,GL.GL_RGBA8,header.width,header.height,0,GL.GL_RGBA,GL.GL_UNSIGNED_BYTE,tile.frame.pixels)
                        for axis in (GL.GL_TEXTURE_WRAP_S,GL.GL_TEXTURE_WRAP_T):
                            GL.glTexParameteri(GL.GL_TEXTURE_2D,axis,GL.GL_CLAMP_TO_EDGE)
                        GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_MIN_FILTER,GL.GL_LINEAR)
                        GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_MAG_FILTER,GL.GL_LINEAR)
                    u0=1.0/(32*header.width);u1=(header.width-1)/header.width
                    v1=(header.height-1)/header.height
                    corners=((tile.left,tile.top,u0,0.),(tile.right,tile.top,u1,0.),
                             (tile.right,tile.bottom,u1,v1),(tile.left,tile.bottom,u0,v1))
                    data=np.ascontiguousarray([[*center,x*instance.scale,y*instance.scale,u,v]
                                               for corner in (0,1,2,0,2,3) for x,y,u,v in (corners[corner],)],np.float32)
                    alpha=tile.frame.pixels[:,:,3]
                    if np.any((alpha>0)&(alpha<255)):
                        translucent.append((tile.texture_id,data,center,instance.object_index,frame_index,instance.upright))
                    else:
                        key=(tile.texture_id,instance.object_index if frame_index >= 0 else -1,frame_index,instance.upright)
                        opaque.setdefault(key,[]).append((instance.object_index,data))
            arrays: list[FloatArray]=[];owners: list[np.ndarray]=[];cursor=0
            for (texture_id,object_index,frame_index,upright),parts in opaque.items():
                data=np.concatenate([part for _,part in parts]);arrays.append(data)
                owners.extend(np.full(len(part),index,np.int32) for index,part in parts)
                self.ranges.append(SpriteDrawRange(texture_id,cursor,len(data),False,np.zeros(3,np.float32),object_index,frame_index,upright));cursor+=len(data)
            for texture_id,data,center,index,frame_index,upright in translucent:
                arrays.append(data);owners.append(np.full(len(data),index,np.int32))
                self.ranges.append(SpriteDrawRange(texture_id,cursor,len(data),True,center,index,frame_index,upright));cursor+=len(data)
            vertices=np.concatenate(arrays) if arrays else np.empty((0,7),np.float32)
            self.vertices=vertices
            self.vertex_objects=np.concatenate(owners) if owners else np.empty(0,np.int32)
            self.local_offsets = self.vertices[:, 3:5].copy()
            for instance in instances:
                if instance.scale > 0:
                    self.local_offsets[self.vertex_objects == instance.object_index] /= instance.scale
            self.vao=int(GL.glGenVertexArrays(1));self.vbo=int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self.vao);GL.glBindBuffer(GL.GL_ARRAY_BUFFER,self.vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER,vertices.nbytes,vertices,GL.GL_DYNAMIC_DRAW)
            for location,count,offset in ((0,3,0),(1,2,12),(2,2,20)):
                GL.glEnableVertexAttribArray(location)
                GL.glVertexAttribPointer(location,count,GL.GL_FLOAT,GL.GL_FALSE,28,ctypes.c_void_p(offset))
            GL.glBindVertexArray(0);GL.glBindBuffer(GL.GL_ARRAY_BUFFER,0)
            GL.glBindTexture(GL.GL_TEXTURE_2D,0);GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT,4)
        except Exception:
            self.delete();raise

    def update_positions(self, instances: tuple[SpriteInstance,...]) -> bool:
        """Reuse textures/program/VAO when an edit changes only world positions."""
        if len(instances) != len(self.instances):
            return False
        for old,new in zip(self.instances,instances):
            def signature(sprite: SpriteInstance) -> tuple:
                return tuple(tuple((tile.texture_id,id(tile.frame),tile.left,tile.right,tile.top,tile.bottom)
                                   for tile in frame) for frame in sprite.frames)
            if signature(old) != signature(new) or (old.frame_speed,old.initial_frame) != (new.frame_speed,new.initial_frame):
                return False
            if (old.object_index,old.sprite_id,len(old.tiles),old.upright) != (new.object_index,new.sprite_id,len(new.tiles),new.upright):
                return False
            if any(a.frame is not b.frame or (a.texture_id,a.left,a.right,a.top,a.bottom) !=
                   (b.texture_id,b.left,b.right,b.top,b.bottom) for a,b in zip(old.tiles,new.tiles)):
                return False
        changed = {new.object_index:new.position for old,new in zip(self.instances,instances) if old.position != new.position}
        scales = {new.object_index:new.scale for old,new in zip(self.instances,instances) if old.scale != new.scale}
        if changed or scales:
            for index, scale in scales.items():
                mask = self.vertex_objects == index
                self.vertices[mask, 3:5] = self.local_offsets[mask] * scale
            for index,position in changed.items():
                self.vertices[self.vertex_objects == index,:3] = position
            for group in self.ranges:
                if group.object_index in changed:
                    group.center[:] = changed[group.object_index]
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER,self.vbo)
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER,0,self.vertices.nbytes,self.vertices)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER,0)
        self.instances=instances
        return True

    def draw(self, matrix: FloatArray, view: FloatArray, camera_position: FloatArray,
             *, transparent_pass: bool = False, seconds: float = 0.0, hidden: frozenset[int] = frozenset(),
             ranges: Sequence[SpriteDrawRange] | None = None, upright_sceneries: bool = True) -> None:
        GL.glUseProgram(self.program);GL.glBindVertexArray(self.vao)
        GL.glUniformMatrix4fv(self.matrix_uniform,1,GL.GL_FALSE,np.ascontiguousarray(matrix.T))
        GL.glUniform3fv(self.right_uniform,1,np.ascontiguousarray(view[0,:3]))
        GL.glUniform3fv(self.up_uniform,1,np.ascontiguousarray(view[1,:3]))
        GL.glUniform3fv(self.position_uniform,1,np.ascontiguousarray(camera_position,dtype=np.float32))
        GL.glDisable(GL.GL_CULL_FACE);GL.glEnable(GL.GL_DEPTH_TEST);GL.glActiveTexture(GL.GL_TEXTURE0)
        groups=(sorted(self.ranges,key=lambda group:(group.translucent,float(view[2,:3]@
                    self.range_center(group,view,camera_position,upright_sceneries)) if group.translucent else 0.))
                if ranges is None else ranges)
        if not transparent_pass:
            self.draw_call_count=0
        frames={instance.object_index:instance.frame_at(seconds) for instance in self.instances if instance.frames}
        try:
            for group in groups:
                if group.object_index in hidden:
                    continue
                if group.animation_frame >= 0 and frames.get(group.object_index) != group.animation_frame:
                    continue
                if group.translucent != transparent_pass:
                    continue
                GL.glUniform1i(self.upright_uniform, int(group.upright and upright_sceneries))
                if group.translucent:
                    GL.glEnable(GL.GL_BLEND);GL.glBlendFunc(GL.GL_SRC_ALPHA,GL.GL_ONE_MINUS_SRC_ALPHA)
                else:GL.glDisable(GL.GL_BLEND)
                GL.glDepthMask(GL.GL_FALSE if group.translucent else GL.GL_TRUE)
                GL.glBindTexture(GL.GL_TEXTURE_2D,self.textures[group.texture_id])
                GL.glDrawArrays(GL.GL_TRIANGLES,group.first,group.count);self.draw_call_count+=1
        finally:
            GL.glDepthMask(GL.GL_TRUE);GL.glDisable(GL.GL_BLEND)
            GL.glBindTexture(GL.GL_TEXTURE_2D,0);GL.glBindVertexArray(0);GL.glUseProgram(0)

    def range_center(self, group: SpriteDrawRange, view: FloatArray, camera_position: FloatArray,
                     upright_sceneries: bool) -> FloatArray:
        """Upright translucent tiles span view depths; sort their displayed centers."""
        if not group.upright or not upright_sceneries:
            return group.center
        right,up = billboard_axes(view,camera_position,group.center,upright=True)
        offset = self.vertices[group.first:group.first+group.count,3:5].mean(axis=0)
        return np.asarray(group.center+right*offset[0]+up*offset[1],np.float32)

    def transparent_draws(self, matrix: FloatArray, view: FloatArray, camera_position: FloatArray,
                          *, seconds: float, hidden: frozenset[int], upright_sceneries: bool = True) -> list[TransparentDraw]:
        frames = {instance.object_index: instance.frame_at(seconds) for instance in self.instances if instance.frames}
        return [TransparentDraw(self.range_center(group,view,camera_position,upright_sceneries), partial(self.draw, matrix, view, camera_position,
                    transparent_pass=True, seconds=seconds, hidden=hidden, ranges=(group,), upright_sceneries=upright_sceneries))
                for group in self.ranges if group.translucent and group.object_index not in hidden
                and (group.animation_frame < 0 or frames.get(group.object_index) == group.animation_frame)]

    def delete(self) -> None:
        if self.textures:GL.glDeleteTextures(list(self.textures.values()));self.textures.clear()
        if self.vbo:GL.glDeleteBuffers(1,[self.vbo]);self.vbo=0
        if self.vao:GL.glDeleteVertexArrays(1,[self.vao]);self.vao=0
        if self.program:GL.glDeleteProgram(self.program);self.program=0
