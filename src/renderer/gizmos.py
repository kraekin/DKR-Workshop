"""Batched color-coded object markers and directional checkpoint/AI paths."""
from __future__ import annotations

import ctypes
from collections.abc import Iterable
import math

import numpy as np
from OpenGL import GL

from src.core.objects import LevelObject, RacePath
from src.renderer.camera import FloatArray

CATEGORY_COLORS: dict[str, tuple[float, float, float]] = {
    'Player spawns': (.2, 1., .45), 'Checkpoints': (.15, .85, 1.),
    'AI nodes': (.85, .4, 1.), 'Weapon balloons': (1., .3, .35),
    'Bananas': (1., .9, .15), 'Speed zippers': (1., .45, .1),
    'Scenery': (.35, .8, .4), 'Sound triggers': (.9, .55, 1.),
    'Animation / cameras': (.5, .65, .9), 'Other gameplay': (.95, .8, .6),
}


def _marker(obj: LevelObject, radius: float) -> FloatArray:
    center = np.asarray(obj.position, dtype=np.float32)
    pairs: list[tuple[FloatArray, FloatArray]] = []
    if obj.category in ('Scenery', 'Other gameplay', 'Animation / cameras'):
        corners = np.array([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)], np.float32)
        pairs.extend((corners[i], corners[i | bit]) for i in range(8) for bit in (1,2,4) if not i & bit)
    else:
        for axis in range(3):
            points = np.zeros((17, 3), np.float32)
            angles = np.linspace(0, 2 * math.pi, 17)
            points[:, (axis + 1) % 3] = np.cos(angles)
            points[:, (axis + 2) % 3] = np.sin(angles)
            pairs.extend(zip(points[:-1], points[1:]))
    if obj.yaw is not None:
        forward = np.array([math.sin(obj.yaw), 0, math.cos(obj.yaw)], np.float32)
        if obj.definition.behavior_id in (11, 13):
            # Starts/checkpoints show travel along local -Z, not the +Z plane normal.
            forward=-forward
        right = np.array([forward[2], 0, -forward[0]], np.float32)
        tip = forward * 2.5
        pairs.extend(((np.zeros(3, np.float32), tip), (tip, forward * 1.5 + right * .5),
                      (tip, forward * 1.5 - right * .5)))
    color = CATEGORY_COLORS[obj.category]
    return np.ascontiguousarray([[*(center + point * radius), *color] for pair in pairs for point in pair], dtype=np.float32)


def _route(path: RacePath, radius: float) -> FloatArray:
    points = path.points
    color = (.8, .4, 1.) if path.kind == 'ai' else ((1., .6, .2) if path.alternate else (.1, .95, .95))
    if path.kind in ('camera', 'cinematic'):
        color = (1., .5, .85) if path.kind == 'camera' else (.3, 1., .55)
    if 'AI lane' in path.name:
        lane = int(path.name[-1])
        color = ((.2,1.,.4),(.2,.65,1.),(1.,.35,.8),(1.,.85,.2))[lane]
    vertices: list[tuple[float, ...]] = []
    for first, second in zip(points[:-1], points[1:]):
        vertices.extend(((*first, *color), (*second, *color)))
    # Arrowheads show traversal direction without changing the source path.
    for index in range(0, len(points) - 1, 12 if path.kind in ('checkpoint', 'camera', 'cinematic') else 1):
        start, end = points[index:index + 2]
        delta = end - start
        length = float(np.linalg.norm(delta))
        if length < 1e-5: continue
        forward = delta / length
        side = np.cross(forward, np.array([0, 1, 0], np.float32))
        if np.linalg.norm(side) < .01: side = np.cross(forward, np.array([1, 0, 0], np.float32))
        side /= max(float(np.linalg.norm(side)), 1e-5)
        size = min(radius * 1.5, length * .8)
        for sign in (-1, 1):
            vertices.extend(((*end, *color), (*(end - forward * size + side * size * sign * .5), *color)))
    return np.ascontiguousarray(vertices, dtype=np.float32).reshape(-1, 6)


class GizmoMesh:
    """Uses the viewport's line shader; resources belong to its GL context."""
    def __init__(self, objects: tuple[LevelObject, ...], paths: tuple[RacePath, ...],
                 radius: float, visible: Iterable[int]) -> None:
        self.vao = self.vbo = 0
        self.ranges: dict[int, tuple[int, int]] = {}
        self.objects = objects
        self.paths = paths
        self.radius = radius
        self.visible = tuple(visible)
        vertices: list[FloatArray] = []
        cursor = 0
        for index in self.visible:
            array = _marker(objects[index], radius)
            self.ranges[index] = (cursor, len(array))
            vertices.append(array); cursor += len(array)
        self.marker_count = cursor
        for path in paths:
            array = _route(path, radius)
            vertices.append(array); cursor += len(array)
        self.path_count = cursor - self.marker_count
        data = np.concatenate(vertices) if vertices else np.empty((0,6), np.float32)
        self.data = data
        self.local_positions = data[:self.marker_count,:3].copy()
        for index,(first,count) in self.ranges.items():
            self.local_positions[first:first+count] -= objects[index].position
        try:
            self.vao = int(GL.glGenVertexArrays(1)); self.vbo = int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self.vao); GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_DYNAMIC_DRAW)
            for location, offset in ((0,0),(1,12)):
                GL.glEnableVertexAttribArray(location)
                GL.glVertexAttribPointer(location, 3, GL.GL_FLOAT, GL.GL_FALSE, 24, ctypes.c_void_p(offset))
            GL.glBindVertexArray(0);GL.glBindBuffer(GL.GL_ARRAY_BUFFER,0)
        except Exception:
            self.delete();raise

    def update_positions(self, objects: tuple[LevelObject,...], paths: tuple[RacePath,...],
                         radius: float, visible: Iterable[int]) -> bool:
        if len(objects) != len(self.objects) or radius != self.radius or tuple(visible) != self.visible:
            return False
        for old,new in zip(self.objects,objects):
            if old.key != new.key or old.definition is not new.definition or old.object_id != new.object_id or old.parameters != new.parameters:
                return False
        changed = False
        for index,(first,count) in self.ranges.items():
            if self.objects[index].position != objects[index].position:
                self.data[first:first+count,:3] = self.local_positions[first:first+count] + objects[index].position
                changed = True
        routes_changed = len(paths) != len(self.paths) or any((a.name,a.kind,a.alternate) != (b.name,b.kind,b.alternate)
                             or not np.array_equal(a.points,b.points) for a,b in zip(self.paths,paths))
        prior_bytes = self.data.nbytes
        if routes_changed:
            arrays = [self.data[:self.marker_count], *(_route(path,radius) for path in paths)]
            self.data = np.ascontiguousarray(np.concatenate(arrays),np.float32)
            self.path_count = len(self.data)-self.marker_count
            changed = True
        if changed:
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER,self.vbo)
            if self.data.nbytes != prior_bytes:
                GL.glBufferData(GL.GL_ARRAY_BUFFER,self.data.nbytes,self.data,GL.GL_DYNAMIC_DRAW)
            else:
                GL.glBufferSubData(GL.GL_ARRAY_BUFFER,0,self.data.nbytes,self.data)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER,0)
        self.objects = objects
        self.paths = paths
        return True

    def draw(self, matrix: FloatArray, uniform: int, *, objects: bool, paths: bool, selected: int | tuple[int, ...]) -> None:
        GL.glBindVertexArray(self.vao)
        GL.glDisable(GL.GL_DEPTH_TEST)
        try:
            GL.glUniformMatrix4fv(uniform, 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
            if paths: GL.glDrawArrays(GL.GL_LINES, self.marker_count, self.path_count)
            if objects: GL.glDrawArrays(GL.GL_LINES, 0, self.marker_count)
            selected_indices = (selected,) if isinstance(selected, int) else selected
            for index in selected_indices if objects else ():
                if index not in self.ranges:
                    continue
                position = np.asarray(self.objects[index].position, np.float32)
                transform = np.eye(4, dtype=np.float32);transform[:3,:3] *= 1.6;transform[:3,3] = position * -.6
                GL.glUniformMatrix4fv(uniform, 1, GL.GL_FALSE, np.ascontiguousarray((matrix @ transform).T))
                GL.glDisableVertexAttribArray(1);GL.glVertexAttrib3f(1,1.,.85,.25)
                first,count = self.ranges[index];GL.glDrawArrays(GL.GL_LINES,first,count)
                GL.glEnableVertexAttribArray(1)
        finally:
            GL.glEnable(GL.GL_DEPTH_TEST);GL.glBindVertexArray(0)

    def delete(self) -> None:
        if self.vbo: GL.glDeleteBuffers(1,[self.vbo]);self.vbo=0
        if self.vao: GL.glDeleteVertexArrays(1,[self.vao]);self.vao=0


class TranslationGizmo:
    """Solid screen-sized arrows using the viewport's existing color shader."""
    def __init__(self) -> None:
        self.vao = self.vbo = 0
        try:
            self.vao = int(GL.glGenVertexArrays(1))
            self.vbo = int(GL.glGenBuffers(1))
            GL.glBindVertexArray(self.vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
            for location, offset in ((0, 0), (1, 12)):
                GL.glEnableVertexAttribArray(location)
                GL.glVertexAttribPointer(location, 3, GL.GL_FLOAT, GL.GL_FALSE, 24, ctypes.c_void_p(offset))
            GL.glBindVertexArray(0)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        except Exception:
            self.delete()
            raise

    def draw(self, matrix: FloatArray, uniform: int, center: FloatArray, length: float,
             view: FloatArray, active: int | None, *, mode: str = "Move", axes: tuple[int, ...] = (0, 1, 2)) -> None:
        vertices: list[tuple[float, ...]] = []

        def triangle(a: FloatArray, b: FloatArray, c: FloatArray, color: tuple[float, float, float]) -> None:
            vertices.extend((*point, *color) for point in (a, b, c))

        for axis, color in enumerate(((1., .23, .23), (.2, 1., .35), (.28, .58, 1.))):
            if mode == "Scale" or (mode == "Rotate" and axis not in axes):
                continue
            if active == axis:
                color = (1., .88, .25)
            if mode == "Rotate":
                for a, b in zip(np.linspace(0, math.tau, 65)[:-1], np.linspace(0, math.tau, 65)[1:]):
                    def ring(angle: float, radius: float) -> FloatArray:
                        point = center.copy()
                        point[(axis + 1) % 3] += math.cos(angle) * length * radius
                        point[(axis + 2) % 3] += math.sin(angle) * length * radius
                        return point
                    triangle(ring(a, .78), ring(a, .82), ring(b, .82), color)
                    triangle(ring(a, .78), ring(b, .82), ring(b, .78), color)
                continue
            direction = np.eye(3, dtype=np.float32)[axis]
            side = np.cross(direction, view[2, :3])
            if np.linalg.norm(side) < .001:
                side = view[0, :3]
            side = side/max(float(np.linalg.norm(side)), .001)
            start, end = center+direction*length*.14, center+direction*length*.79
            width = side*length*.018
            triangle(start-width, start+width, end+width, color)
            triangle(start-width, end+width, end-width, color)
            triangle(center+direction*length, end+side*length*.075, end-side*length*.075, color)
        if mode == "Scale":
            end = center + (view[0, :3] + view[1, :3]) * length * .7
            side = (view[0, :3] - view[1, :3]) * length * .015
            triangle(center - side, center + side, end + side, (.95, .95, .95))
            triangle(center - side, end + side, end - side, (.95, .95, .95))
            right, up = view[0, :3] * length * .07, view[1, :3] * length * .07
            triangle(end-right-up, end+right-up, end+right+up, (.95, .95, .95))
            triangle(end-right-up, end+right+up, end-right+up, (.95, .95, .95))
        right, up = view[0, :3]*length*.06, view[1, :3]*length*.06
        color = (1., .88, .25) if active == -1 else (.95, .95, .95)
        if mode != "Rotate":
            triangle(center-right-up, center+right-up, center+right+up, color)
            triangle(center-right-up, center+right+up, center-right+up, color)
        data = np.ascontiguousarray(vertices, dtype=np.float32)
        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_STREAM_DRAW)
        GL.glUniformMatrix4fv(uniform, 1, GL.GL_FALSE, np.ascontiguousarray(matrix.T))
        GL.glDisable(GL.GL_DEPTH_TEST)
        try:
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(data))
        finally:
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glBindVertexArray(0)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)

    def delete(self) -> None:
        if self.vbo: GL.glDeleteBuffers(1, [self.vbo]); self.vbo = 0
        if self.vao: GL.glDeleteVertexArrays(1, [self.vao]); self.vao = 0
