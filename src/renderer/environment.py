"""Environment GL state: sky/background, shared fog UBO and water preview."""
from __future__ import annotations

import ctypes
from functools import partial
import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader

from src.core.environment import WaterPreview, flashy_sky, fog_defaults, texture_frame
from src.core.level_header import LevelHeader
from src.core.object_models import ObjectLibrary
from src.core.objects import ObjectDefinition
from src.core.textures import Texture
from src.renderer.shaders import (BACKGROUND_FRAGMENT, BACKGROUND_VERTEX,
                                  TRACK_FRAGMENT_SHADER, TRACK_VERTEX_SHADER, WATER_FRAGMENT)
from src.renderer.track_mesh import TrackMesh
from src.renderer.transparency import TransparentDraw


class SurfaceMesh:
    """One persistent dynamic buffer and all frames of a transient surface."""
    def __init__(self, texture: Texture, detail: Texture | None = None) -> None:
        self.texture = texture
        self.detail = detail
        self.detail_frame: int = 0
        self.vao = self.vbo = self.program = 0
        self.handles: list[int] = []
        self.detail_handles: list[int] = []
        self.size = 0
        try:
            self.program = int(compileProgram(compileShader(TRACK_VERTEX_SHADER, GL.GL_VERTEX_SHADER),
                                              compileShader(WATER_FRAGMENT if detail else TRACK_FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER)))
            self.uniforms = {name: int(GL.glGetUniformLocation(self.program, name)) for name in
                ('u_view_projection', 'u_vertex_colors', 'u_wireframe', 'u_textured', 'u_vertex_alpha', 'u_texture')}
            for frame, handles in [(f, self.handles) for f in texture.frames] + ([(f, self.detail_handles) for f in detail.frames] if detail else []):
                handle = int(GL.glGenTextures(1)); handles.append(handle)
                GL.glBindTexture(GL.GL_TEXTURE_2D, handle)
                GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
                h = frame.header
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, h.width, h.height, 0,
                                GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, frame.pixels)
                for axis, clamp in ((GL.GL_TEXTURE_WRAP_S, h.clamp_u), (GL.GL_TEXTURE_WRAP_T, h.clamp_v)):
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, axis, GL.GL_CLAMP_TO_EDGE if clamp else GL.GL_REPEAT)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            self.vao = int(GL.glGenVertexArrays(1)); self.vbo = int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self.vao); GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
            for location, count, offset in ((0, 3, 0), (1, 4, 12), (2, 2, 28)):
                GL.glEnableVertexAttribArray(location)
                GL.glVertexAttribPointer(location, count, GL.GL_FLOAT, GL.GL_FALSE, 36, ctypes.c_void_p(offset))
        except Exception:
            self.delete()
            raise
        finally:
            GL.glBindVertexArray(0); GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0); GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 4)

    def draw(self, vertices: np.ndarray, matrix: np.ndarray, frame: int, *,
             blend: bool, textured: bool, wireframe: bool = False) -> None:
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        if self.size != vertices.nbytes:
            GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_DYNAMIC_DRAW)
            self.size = vertices.nbytes
        else:
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glUseProgram(self.program); GL.glBindVertexArray(self.vao)
        GL.glUniformMatrix4fv(self.uniforms['u_view_projection'], 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
        for name, value in (('u_vertex_colors', 1), ('u_vertex_alpha', 1), ('u_textured', int(textured)), ('u_wireframe', 0), ('u_texture', 0)):
            GL.glUniform1i(self.uniforms[name], value)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glActiveTexture(GL.GL_TEXTURE0); GL.glBindTexture(GL.GL_TEXTURE_2D, self.handles[frame % len(self.handles)])
        if self.detail is not None:
            GL.glUniform1i(GL.glGetUniformLocation(self.program, 'u_detail'), 1)
            base, detail_header = self.texture.frames[0].header, self.detail.frames[0].header
            GL.glUniform2f(GL.glGetUniformLocation(self.program, 'u_detail_scale'), base.width/detail_header.width, base.height/detail_header.height)
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.detail_handles[self.detail_frame % len(self.detail_handles)])
        if blend:
            GL.glEnable(GL.GL_BLEND); GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDepthMask(GL.GL_FALSE if blend else GL.GL_TRUE)
        try:
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(vertices))
            if wireframe:
                GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE)
                GL.glDepthFunc(GL.GL_LEQUAL)
                GL.glUniform1i(self.uniforms['u_wireframe'], 1)
                GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(vertices))
        finally:
            GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL); GL.glDepthFunc(GL.GL_LESS)
            GL.glDepthMask(GL.GL_TRUE); GL.glDisable(GL.GL_BLEND)
            GL.glActiveTexture(GL.GL_TEXTURE1); GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0); GL.glBindVertexArray(0); GL.glUseProgram(0)

    def delete(self) -> None:
        if self.handles:
            GL.glDeleteTextures(self.handles); self.handles.clear()
        if self.detail_handles:
            GL.glDeleteTextures(self.detail_handles); self.detail_handles.clear()
        if self.vbo:
            GL.glDeleteBuffers(1, [self.vbo]); self.vbo = 0
        if self.vao:
            GL.glDeleteVertexArrays(1, [self.vao]); self.vao = 0
        if self.program:
            GL.glDeleteProgram(self.program); self.program = 0


class EnvironmentRenderer:
    def __init__(self) -> None:
        self.ubo = self.vao = self.program = 0
        self.sky: TrackMesh | None = None
        self.water: SurfaceMesh | None = None
        self.flash: SurfaceMesh | None = None
        self.header: LevelHeader | None = None
        self.sky_definition: ObjectDefinition | None = None
        self.water_preview: WaterPreview | None = None
        try:
            self.ubo = int(GL.glGenBuffers(1)); GL.glBindBuffer(GL.GL_UNIFORM_BUFFER, self.ubo)
            GL.glBufferData(GL.GL_UNIFORM_BUFFER, 32, np.zeros(8, np.float32), GL.GL_DYNAMIC_DRAW)
            GL.glBindBufferBase(GL.GL_UNIFORM_BUFFER, 0, self.ubo)
            GL.glBindBuffer(GL.GL_UNIFORM_BUFFER, 0)
            self.vao = int(GL.glGenVertexArrays(1))
            self.program = int(compileProgram(compileShader(BACKGROUND_VERTEX, GL.GL_VERTEX_SHADER),
                                              compileShader(BACKGROUND_FRAGMENT, GL.GL_FRAGMENT_SHADER)))
        except Exception:
            self.delete()
            raise

    def configure(self, header: LevelHeader | None, library: ObjectLibrary | None,
                  sky: ObjectDefinition | None, water: WaterPreview | None,
                  textures: dict[int, Texture], flash: Texture | None) -> None:
        for item in (self.sky, self.water, self.flash):
            if item is not None:
                item.delete()
        self.sky = self.water = self.flash = None
        self.header, self.sky_definition, self.water_preview = header, sky, water
        if header is not None and sky is not None and sky.model_type == 0 and sky.model_ids and library is not None:
            self.sky = TrackMesh(library.model(sky.model_ids[0]).mesh, library.textures)
        if water is not None:
            self.water = SurfaceMesh(textures[water.texture_id], water.detail)
        if flash is not None:
            self.flash = SurfaceMesh(flash)

    def fog(self, enabled: bool) -> None:
        values = np.zeros(8, np.float32)
        if self.header is not None:
            near, far, color, active = fog_defaults(self.header)
            values[:] = (near, far, 0., 0., *color, float(enabled and active))
        GL.glBindBuffer(GL.GL_UNIFORM_BUFFER, self.ubo)
        GL.glBufferSubData(GL.GL_UNIFORM_BUFFER, 0, values.nbytes, values)
        GL.glBindBufferBase(GL.GL_UNIFORM_BUFFER, 0, self.ubo)
        GL.glBindBuffer(GL.GL_UNIFORM_BUFFER, 0)

    def background(self, matrix: np.ndarray, camera: np.ndarray, yaw: float, seconds: float,
                   *, enabled: bool, gradient: bool, textured: bool, motion: bool) -> None:
        self.fog(False)
        if self.header is None or not enabled:
            return
        h = self.header
        bottom = h.background_bottom if gradient else h.background_color
        top = h.background_top if gradient else h.background_color
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(GL.GL_FALSE)
        try:
            GL.glUseProgram(self.program); GL.glBindVertexArray(self.vao)
            GL.glUniform3fv(GL.glGetUniformLocation(self.program, 'u_bottom'), 1, np.array(bottom, np.float32)/255)
            GL.glUniform3fv(GL.glGetUniformLocation(self.program, 'u_top'), 1, np.array(top, np.float32)/255)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
            GL.glBindVertexArray(0); GL.glUseProgram(0)
            if gradient:
                return
            if self.sky is not None and self.sky_definition is not None:
                transform = np.eye(4, dtype=np.float32)
                transform[:3, :3] *= self.sky_definition.scale
                if h.special_sky == 0:
                    transform[:3, 3] = camera
                self.sky.draw(matrix@transform, vertex_colors=True, wireframe=False, cull_backfaces=False,
                    isolated_segment=-1, textured=textured, camera_position=np.zeros(3, np.float32))
            if self.flash is not None:
                tex = self.flash.texture
                t = seconds if motion else 0.
                frame = int(t*60*tex.frames[0].header.frame_advance)//256 % len(tex.frames)
                self.flash.draw(flashy_sky(h, tex, camera, yaw, t), matrix, frame, blend=True, textured=textured)
        finally:
            GL.glDepthMask(GL.GL_TRUE); GL.glEnable(GL.GL_DEPTH_TEST)

    def draw_water(self, matrix: np.ndarray, seconds: float, *, textured: bool, wireframe: bool,
                   vertices: np.ndarray | None = None) -> None:
        if self.water is None or self.water_preview is None:
            return
        texture = self.water.texture
        self.water.detail_frame = (int(max(0., seconds)*60*self.water.detail.frames[0].header.frame_advance)//256
                                   if self.water.detail else 0)
        frame = texture_frame(texture, self.water_preview.batch, seconds) if self.water_preview.batch is not None else 0
        self.water.draw(self.water_preview.buffer(texture, seconds) if vertices is None else vertices, matrix, frame,
                        blend=self.water_preview.settings.translucent, textured=textured, wireframe=wireframe)

    def transparent_draws(self, matrix: np.ndarray, seconds: float, *,
                          textured: bool, wireframe: bool) -> list[TransparentDraw]:
        if self.water is None or self.water_preview is None or not self.water_preview.settings.translucent:
            return []
        vertices = self.water_preview.buffer(self.water.texture, seconds)
        return [TransparentDraw(vertices[:, :3].mean(axis=0), partial(self.draw_water, matrix, seconds,
                    textured=textured, wireframe=wireframe, vertices=vertices))]

    def delete(self) -> None:
        for item in (self.sky, self.water, self.flash):
            if item is not None:
                item.delete()
        self.sky = self.water = self.flash = None
        if self.ubo:
            GL.glDeleteBuffers(1, [self.ubo]); self.ubo = 0
        if self.vao:
            GL.glDeleteVertexArrays(1, [self.vao]); self.vao = 0
        if self.program:
            GL.glDeleteProgram(self.program); self.program = 0
