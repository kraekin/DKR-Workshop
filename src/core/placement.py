"""Existing-entry placement operations and track raycasting, without Qt/GL.

Transform registry follows local object_functions.c:113,1780,3194,3505,4647
and include/level_object_entries.h. Unknown transform meanings stay disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from collections.abc import Mapping

import numpy as np
from numpy.typing import NDArray

from src.core.level_model import LevelModel
from src.core.objects import LevelObject

ObjectKey = tuple[int, int]
FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class TransformSpec:
    angles: tuple[str | None, str | None, str | None] = (None, None, None)
    units: int = 64
    scale: str | None = None
    minimum_scale: int = 10


TRANSFORMS: dict[int, TransformSpec] = {
    2: TransformSpec((None, "angleY", None), scale="radius"),
    13: TransformSpec((None, "angleY", None)),  # Path scale is not artwork scale.
    14: TransformSpec((None, "closedRotation", None), scale="scale"),
    17: TransformSpec(scale="scale"),
    49: TransformSpec(("x_rotation", "y_rotation", "z_rotation"), 256, "scale", 1),
}


def rotation_axes(objects: tuple[LevelObject, ...]) -> tuple[int, ...]:
    if not objects:
        return ()
    # Multi-object rotation uses the common world yaw axis. Single controller
    # pitch/roll handles edit its stored Euler component, with no orbiting.
    candidates = (0, 1, 2) if len(objects) == 1 else (1,)
    return tuple(axis for axis in candidates if all(
        (spec := TRANSFORMS.get(obj.definition.behavior_id)) is not None
        and spec.angles[axis] is not None and obj.value(spec.angles[axis]) is not None
        for obj in objects))


def can_scale(objects: tuple[LevelObject, ...]) -> bool:
    return bool(objects) and all((spec := TRANSFORMS.get(obj.definition.behavior_id)) is not None
                                 and spec.scale is not None and obj.value(spec.scale) is not None for obj in objects)


def patch_entry(obj: LevelObject, *, position: tuple[int, int, int] | None = None,
                parameters: Mapping[str, int | tuple[int, ...]] | None = None) -> bytes:
    if obj.raw_data is None:
        raise ValueError("Placement editing requires original ROM entry bytes")
    raw = bytearray(obj.raw_data)
    if position is not None:
        if len(position) != 3 or any(type(v) is not int or not -32768 <= v <= 32767 for v in position):
            raise ValueError("Position must contain three signed16 integers")
        struct.pack_into(">3h", raw, 2, *position)
    for name, value in (parameters or {}).items():
        parameter = next((p for p in obj.parameters if p.name == name), None)
        if parameter is None:
            raise ValueError(f"{obj.definition.name} has no field {name}")
        count = len(parameter.value) if isinstance(parameter.value, tuple) else 1
        values = value if isinstance(value, tuple) else (value,)
        if len(values) != count or any(type(v) is not int for v in values):
            raise ValueError(f"{name} needs {count} integer value(s)")
        try:
            struct.pack_into(">" + str(count) + parameter.format, raw, parameter.offset, *values)
        except struct.error as error:
            raise ValueError(str(error)) from error
    return bytes(raw)


def translated_entries(objects: tuple[LevelObject, ...], delta: tuple[float, float, float]) -> dict[ObjectKey, bytes]:
    positions = np.asarray([obj.position for obj in objects], np.float64)
    shift = np.asarray(delta, np.float64)
    if not len(objects) or shift.shape != (3,) or not np.isfinite(shift).all():
        raise ValueError("Select objects and a finite XYZ displacement")
    # Clamp one common displacement, preserving relative spacing at s16 limits.
    shift = np.clip(np.rint(shift), np.max(-32768 - positions, axis=0), np.min(32767 - positions, axis=0))
    return {obj.key: patch_entry(obj, position=tuple(int(v) for v in point))
            for obj, point in zip(objects, positions + shift)}


def aligned_entries(objects: tuple[LevelObject, ...], axis: int) -> dict[ObjectKey, bytes]:
    if not objects or axis not in (0, 1, 2):
        raise ValueError("Select objects and an alignment axis")
    entries: dict[ObjectKey, bytes] = {}
    for obj in objects:
        point = list(obj.position)
        point[axis] = objects[0].position[axis]
        entries[obj.key] = patch_entry(obj, position=tuple(point))
    return entries


def rotated_entries(objects: tuple[LevelObject, ...], axis: int, degrees: float) -> dict[ObjectKey, bytes]:
    if axis not in rotation_axes(objects) or not math.isfinite(degrees):
        raise ValueError("Selected objects do not share a verified rotation axis")
    units = min(TRANSFORMS[obj.definition.behavior_id].units for obj in objects)
    degrees = float(np.rint(degrees * units / 360) * 360 / units)
    if abs(math.remainder(degrees, 360)) < 1e-9:
        return {obj.key: obj.raw_data for obj in objects}
    pivot = np.asarray(objects[0].position, np.float64)
    angle = math.radians(degrees)
    direction = np.eye(3)[axis]
    result: dict[ObjectKey, bytes] = {}
    for obj in objects:
        spec = TRANSFORMS[obj.definition.behavior_id]
        name = spec.angles[axis]
        assert name is not None
        delta = int(np.rint(degrees * spec.units / 360))
        parameter = next(p for p in obj.parameters if p.name == name)
        bits = struct.calcsize(">" + parameter.format) * 8
        value = (int(parameter.value) + delta) % (1 << bits)
        if parameter.format.islower() and value >= 1 << (bits - 1):
            value -= 1 << bits
        vector = np.asarray(obj.position, np.float64) - pivot
        point = pivot + vector * math.cos(angle) + np.cross(direction, vector) * math.sin(angle) + direction * np.dot(direction, vector) * (1 - math.cos(angle))
        if np.any(point < -32768) or np.any(point > 32767):
            raise ValueError("Rotation exceeds signed16 coordinates")
        result[obj.key] = patch_entry(obj, position=tuple(int(v) for v in np.rint(point)), parameters={name: value})
    return result


def scaled_entries(objects: tuple[LevelObject, ...], factor: float) -> dict[ObjectKey, bytes]:
    if not can_scale(objects) or not math.isfinite(factor) or factor <= 0:
        raise ValueError("Select objects with a verified scale and a positive factor")
    if abs(factor - 1) < 1e-9:
        return {obj.key: obj.raw_data for obj in objects}
    pivot = np.asarray(objects[0].position, np.float64)
    result: dict[ObjectKey, bytes] = {}
    for obj in objects:
        spec = TRANSFORMS[obj.definition.behavior_id]
        assert spec.scale is not None
        value = int(np.rint(max(int(obj.value(spec.scale)), spec.minimum_scale) * factor))
        if not spec.minimum_scale <= value <= 255:
            raise ValueError(f"Scale must remain in {spec.minimum_scale}..255 raw units")
        point = pivot + (np.asarray(obj.position, np.float64) - pivot) * factor
        if np.any(point < -32768) or np.any(point > 32767):
            raise ValueError("Scaling exceeds signed16 coordinates")
        result[obj.key] = patch_entry(obj, position=tuple(int(v) for v in np.rint(point)), parameters={spec.scale: value})
    return result


def shared_parameter_entries(objects: tuple[LevelObject, ...], name: str, value: int | tuple[int, ...]) -> dict[ObjectKey, bytes]:
    formats = {next(((p.format, len(p.value) if isinstance(p.value, tuple) else 1) for p in obj.parameters if p.name == name), None) for obj in objects}
    if not objects or None in formats or len(formats) != 1:
        raise ValueError("The selected objects do not share that field's stored type")
    return {obj.key: patch_entry(obj, parameters={name: value}) for obj in objects}


@dataclass(frozen=True)
class TerrainSurface:
    triangles: FloatArray

    @classmethod
    def from_model(cls, model: LevelModel, segment: int = -1) -> TerrainSurface:
        arrays: list[FloatArray] = []
        for part in model.segments:
            if segment >= 0 and part.index != segment:
                continue
            records = (*part.batches, part.terminal_batch)
            for batch, end in zip(records[:-1], records[1:]):
                if not batch.hidden:
                    arrays.append(part.vertices[part.indices[batch.faces_offset:end.faces_offset]])
        triangles = np.ascontiguousarray(np.concatenate(arrays) if arrays else np.empty((0, 3, 3)), np.float64)
        triangles.setflags(write=False)
        return cls(triangles)

    def raycast(self, origin: FloatArray, direction: FloatArray) -> FloatArray | None:
        start, ray = np.asarray(origin, np.float64), np.asarray(direction, np.float64)
        if start.shape != (3,) or ray.shape != (3,) or not np.isfinite(start).all() or not np.isfinite(ray).all() or np.linalg.norm(ray) < 1e-10:
            raise ValueError("Terrain ray must be finite and nonzero")
        if not len(self.triangles):
            return None
        ray = ray / np.linalg.norm(ray)
        a = self.triangles[:, 0]
        edge1, edge2 = self.triangles[:, 1] - a, self.triangles[:, 2] - a
        cross = np.cross(ray, edge2)
        det = np.einsum("ij,ij->i", edge1, cross)
        valid = np.abs(det) > 1e-9
        inv = np.divide(1., det, out=np.zeros_like(det), where=valid)
        offset = start - a
        u = np.einsum("ij,ij->i", offset, cross) * inv
        q = np.cross(offset, edge1)
        v = q @ ray * inv
        distance = np.einsum("ij,ij->i", edge2, q) * inv
        valid &= (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7) & (distance >= 0)
        if not valid.any():
            return None
        return start + ray * float(distance[valid].min())

    def surface_y(self, position: tuple[int, int, int], *, drop: bool, offset: int = 0) -> int | None:
        if not len(self.triangles):
            return None
        x, y, z = position
        start_y = y + .01 if drop else float(self.triangles[:, :, 1].max()) + 1
        point = self.raycast(np.array([x, start_y, z]), np.array([0, -1, 0]))
        if point is None:
            return None
        height = int(np.rint(point[1])) + offset
        if not -32768 <= height <= 32767:
            raise ValueError("Surface placement exceeds signed16 height")
        return height
