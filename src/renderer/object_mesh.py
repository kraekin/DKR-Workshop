"""Shared GPU object geometry; animated positions update existing VBOs."""
from __future__ import annotations

from functools import partial
from collections import OrderedDict
import numpy as np
from OpenGL import GL

from src.core.object_models import ModelInstance, ObjectLibrary, preview_colors
from src.renderer.track_mesh import TrackMesh, DrawRange
from src.renderer.transparency import TransparentDraw


def instance_pose(library: ObjectLibrary, instance: ModelInstance, seconds: float,
                  clip_override: int = -1) -> np.ndarray:
    model = library.model(instance.model_id)
    if instance.clip_index < 0 and clip_override < 0:
        return model.mesh.segments[0].vertices
    clip = library.clip(instance.model_id, instance.clip_index if clip_override < 0 else clip_override)
    if clip is None:
        return model.mesh.segments[0].vertices
    frame = instance.sampled_frame if instance.sampled_frame is not None and clip_override < 0 else (
        instance.initial_frame+int(seconds*60*instance.frame_speed)) % ((clip.frame_count-1)*16)
    if instance.sampled_frame is not None and frame == (clip.frame_count-1)*16:
        # An explicit editor scrub can inspect the stored interpolation endpoint.
        vertices = model.mesh.segments[0].vertices.copy()
        moving = model.animated_indices >= 0
        vertices[moving] = clip.positions[-1][model.animated_indices[moving]]
        return vertices
    return clip.pose(model, frame)


class ObjectMesh:
    def __init__(self, library: ObjectLibrary, instances: tuple[ModelInstance,...]) -> None:
        self.library = library
        self.meshes: dict[int, TrackMesh] = {}
        self.buffers: dict[int, np.ndarray] = {}
        self.current_poses: dict[int, np.ndarray] = {}
        self._pose_buffers: OrderedDict[tuple[int, bytes], np.ndarray] = OrderedDict()
        try:
            for instance in instances:
                if instance.model_id in self.meshes:
                    continue
                model = library.model(instance.model_id).mesh
                self.meshes[instance.model_id] = TrackMesh(model,library.textures)
                # The track renderer expands each triangle into three corners.
                from src.core.textures import model_uvs
                corners = model.flat_vertices[model.indices].reshape(-1,7)
                self.buffers[instance.model_id] = np.ascontiguousarray(np.column_stack((
                    corners,model_uvs(model,library.textures).reshape(-1,2))),np.float32)
        except Exception:
            self.delete()
            raise

    def draw(self, instances: tuple[ModelInstance,...], matrix: np.ndarray, camera: np.ndarray,
             seconds: float, selected: int, clip_override: int, *, textured: bool,
             wireframe: bool, culling: bool, transparent: bool) -> None:
        for instance in instances:
            if not instance.visible:
                continue
            mesh = self.meshes[instance.model_id]
            if transparent and (not textured or not any(group.translucent for group in mesh.ranges)):
                continue
            self._draw_instance(instance, matrix, camera, seconds, selected, clip_override,
                                textured=textured, wireframe=wireframe, culling=culling, transparent=transparent)

    def _draw_instance(self, instance: ModelInstance, matrix: np.ndarray, camera: np.ndarray,
                       seconds: float, selected: int, clip_override: int, *, textured: bool,
                       wireframe: bool, culling: bool, transparent: bool,
                       ranges: tuple[DrawRange, ...] | None = None, pose: np.ndarray | None = None) -> None:
        mesh = self.meshes[instance.model_id]
        model = self.library.model(instance.model_id)
        if pose is None:
            pose = instance_pose(self.library, instance, seconds, clip_override if instance.object_index == selected else -1)
        previous = self.current_poses.get(instance.model_id)
        if previous is None or not np.array_equal(previous, pose):
            key = instance.model_id, pose.tobytes()
            buffer = self._pose_buffers.get(key)
            if buffer is None:
                buffer = self.buffers[instance.model_id].copy()
                buffer[:, :3] = pose[model.mesh.indices].reshape(-1, 3)
                buffer[:, 3:7] = preview_colors(model, pose)[model.mesh.indices].reshape(-1, 4)
                self._pose_buffers[key] = buffer
                if len(self._pose_buffers) > 16:
                    self._pose_buffers.popitem(last=False)
            self._pose_buffers.move_to_end(key)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, mesh.vbo)
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, buffer.nbytes, buffer)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            self.current_poses[instance.model_id] = pose
        transform = instance.transform
        local_camera = np.linalg.solve(transform, np.array([*camera, 1.], np.float32))[:3] if instance.scale else camera
        mesh.draw(matrix@transform, vertex_colors=True, wireframe=wireframe, cull_backfaces=culling,
            isolated_segment=-1, textured=textured, camera_position=local_camera, transparent_pass=transparent, ranges=ranges)

    def transparent_draws(self, instances: tuple[ModelInstance, ...], matrix: np.ndarray, camera: np.ndarray,
                          seconds: float, selected: int, clip_override: int, *, textured: bool,
                          wireframe: bool, culling: bool) -> list[TransparentDraw]:
        draws: list[TransparentDraw] = []
        for instance in instances:
            mesh = self.meshes[instance.model_id]
            groups = tuple(group for group in mesh.ranges if group.translucent) if textured and instance.visible else ()
            if not groups:
                continue
            pose = instance_pose(self.library, instance, seconds, clip_override if instance.object_index == selected else -1)
            corners = pose[self.library.model(instance.model_id).mesh.indices].reshape(-1, 3)
            transform = instance.transform
            for group in groups:
                local = corners[mesh._elements[group.first_index:group.first_index+group.index_count]].mean(axis=0)
                center = transform[:3, :3]@local + transform[:3, 3]
                draws.append(TransparentDraw(center, partial(self._draw_instance, instance, matrix, camera,
                    seconds, selected, clip_override, textured=textured, wireframe=wireframe, culling=culling,
                    transparent=True, ranges=(group,), pose=pose)))
        return draws

    def delete(self) -> None:
        for mesh in self.meshes.values():
            mesh.delete()
        self.meshes.clear()
        self._pose_buffers.clear()
