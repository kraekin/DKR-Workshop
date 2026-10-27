"""Persistent GL resources for procedural animals, portraits and ground decals."""
from __future__ import annotations

import ctypes
from functools import partial
import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader

from src.core.special_art import SpecialInstance
from src.renderer.shaders import TRACK_VERTEX_SHADER, TRACK_FRAGMENT_SHADER
from src.renderer.transparency import TransparentDraw

SpecialDrawRange = tuple[SpecialInstance, int, int, np.ndarray]


class SpecialMesh:
    def __init__(self, instances: tuple[SpecialInstance, ...]) -> None:
        self.program = self.vao = self.vbo = 0
        self.textures: dict[int, int] = {}
        self.blended: dict[int, bool] = {}
        self.instances = instances
        self._pose_key: tuple[float, int] | None = None
        self._capacity = 0
        self.ranges: list[SpecialDrawRange] = []
        try:
            self.program = int(compileProgram(compileShader(TRACK_VERTEX_SHADER, GL.GL_VERTEX_SHADER),
                                              compileShader(TRACK_FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER)))
            self.uniforms = {name: int(GL.glGetUniformLocation(self.program, name)) for name in
                ('u_view_projection', 'u_vertex_colors', 'u_wireframe', 'u_textured', 'u_vertex_alpha', 'u_texture')}
            for instance in instances:
                frame = instance.texture
                if id(frame) in self.textures:
                    continue
                handle = int(GL.glGenTextures(1))
                self.textures[id(frame)] = handle
                GL.glBindTexture(GL.GL_TEXTURE_2D, handle)
                GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
                h = frame.header
                self.blended[id(frame)] = bool(np.any((frame.pixels[:, :, 3] > 0) & (frame.pixels[:, :, 3] < 255)))
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, h.width, h.height, 0,
                                GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, frame.pixels)
                for axis, clamp in ((GL.GL_TEXTURE_WRAP_S, h.clamp_u), (GL.GL_TEXTURE_WRAP_T, h.clamp_v)):
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, axis, GL.GL_CLAMP_TO_EDGE if clamp else GL.GL_REPEAT)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            self.vao = int(GL.glGenVertexArrays(1))
            self.vbo = int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self.vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
            for location, count, offset in ((0, 3, 0), (1, 4, 12), (2, 2, 28)):
                GL.glEnableVertexAttribArray(location)
                GL.glVertexAttribPointer(location, count, GL.GL_FLOAT, GL.GL_FALSE, 36, ctypes.c_void_p(offset))
        except Exception:
            self.delete()
            raise
        finally:
            GL.glBindVertexArray(0)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 4)

    def update_instances(self, instances: tuple[SpecialInstance, ...]) -> bool:
        if {id(item.texture) for item in instances} != set(self.textures):
            return False
        self.instances = instances
        self._pose_key = None
        return True

    def _upload(self, seconds: float) -> None:
        key = seconds, id(self.instances)
        if self._pose_key == key:
            return
        parts: list[np.ndarray] = []
        self.ranges.clear()
        first = 0
        for instance in self.instances:
            corners = instance.pose(seconds)[instance.indices].reshape(-1, 3)
            colors = np.ones((len(corners), 4), np.float32)
            colors[:, 3] = instance.alpha
            parts.append(np.column_stack((corners, colors, instance.uvs.reshape(-1, 2))))
            self.ranges.append((instance, first, len(corners), corners.mean(axis=0)))
            first += len(corners)
        vertices = np.ascontiguousarray(np.concatenate(parts), np.float32)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        if self._capacity != vertices.nbytes:
            GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_DYNAMIC_DRAW)
            self._capacity = vertices.nbytes
        else:
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self._pose_key = key

    def draw(self, matrix: np.ndarray, camera: np.ndarray, seconds: float, *,
             transparent: bool, textured: bool, wireframe: bool,
             ranges: tuple[SpecialDrawRange, ...] | None = None) -> None:
        self._upload(seconds)
        GL.glUseProgram(self.program)
        GL.glUniformMatrix4fv(self.uniforms['u_view_projection'], 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
        GL.glUniform1i(self.uniforms['u_texture'], 0)
        GL.glUniform1i(self.uniforms['u_vertex_colors'], 1)
        GL.glUniform1i(self.uniforms['u_vertex_alpha'], 1)
        GL.glUniform1i(self.uniforms['u_wireframe'], 0)
        GL.glUniform1i(self.uniforms['u_textured'], int(textured))
        GL.glBindVertexArray(self.vao)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glFrontFace(GL.GL_CCW)
        GL.glCullFace(GL.GL_BACK)
        try:
            groups = ranges if ranges is not None else (
                sorted(self.ranges, key=lambda item: -float(np.sum((item[3]-camera)**2))) if transparent else self.ranges)
            for instance, first, count, _ in groups:
                blended = instance.kind == 'zipper' or self.blended[id(instance.texture)]
                if blended != transparent:
                    continue
                if instance.kind in ('fish', 'butterfly'):
                    GL.glEnable(GL.GL_CULL_FACE)  # explicit reverse faces already supply the second side
                else:
                    GL.glDisable(GL.GL_CULL_FACE)  # BACKFACE_DRAW
                if blended:
                    GL.glEnable(GL.GL_BLEND)
                    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
                else:
                    GL.glDisable(GL.GL_BLEND)
                GL.glDepthMask(GL.GL_FALSE if blended else GL.GL_TRUE)
                if instance.kind == 'zipper':
                    GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glPolygonOffset(-1., -1.)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.textures[id(instance.texture)])
                GL.glDrawArrays(GL.GL_TRIANGLES, first, count)
                GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
                if wireframe:
                    GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE)
                    GL.glDepthFunc(GL.GL_LEQUAL)
                    GL.glUniform1i(self.uniforms['u_wireframe'], 1)
                    GL.glDrawArrays(GL.GL_TRIANGLES, first, count)
                    GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
                    GL.glDepthFunc(GL.GL_LESS)
                    GL.glUniform1i(self.uniforms['u_wireframe'], 0)
        finally:
            GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
            GL.glDisable(GL.GL_BLEND)
            GL.glDisable(GL.GL_CULL_FACE)
            GL.glDepthMask(GL.GL_TRUE)
            GL.glDepthFunc(GL.GL_LESS)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glBindVertexArray(0)
            GL.glUseProgram(0)

    def transparent_draws(self, matrix: np.ndarray, camera: np.ndarray, seconds: float, *,
                          textured: bool, wireframe: bool) -> list[TransparentDraw]:
        self._upload(seconds)
        return [TransparentDraw(group[3], partial(self.draw, matrix, camera, seconds,
                    transparent=True, textured=textured, wireframe=wireframe, ranges=(group,)))
                for group in self.ranges if group[0].kind == 'zipper' or self.blended[id(group[0].texture)]]

    def delete(self) -> None:
        if self.textures:
            GL.glDeleteTextures(list(self.textures.values()))
            self.textures.clear()
        if self.vbo:
            GL.glDeleteBuffers(1, [self.vbo])
            self.vbo = 0
        if self.vao:
            GL.glDeleteVertexArrays(1, [self.vao])
            self.vao = 0
        if self.program:
            GL.glDeleteProgram(self.program)
            self.program = 0
