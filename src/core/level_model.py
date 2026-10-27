"""Headless segmented track parser, verified against include/structs.h/tracks.c.

All pointers consumed here are offsets from the decompressed model base.
Runtime collision buffers are deliberately not interpreted as serialized data.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import TypeVar

import numpy as np
from numpy.typing import NDArray

from src.core.rom import AssetError, AssetType, DecompAssets, RomImage

FloatArray = NDArray[np.float32]
IndexArray = NDArray[np.uint32]
ByteArray = NDArray[np.uint8]
UVArray = NDArray[np.int16]
Scalar = TypeVar("Scalar", bound=np.generic)
MODEL_HEADER_SIZE: int = 0x4C
SEGMENT_SIZE: int = 0x44
BATCH_STRUCT: struct.Struct = struct.Struct(">BbhhBBI")
VERTEX_DTYPE: np.dtype = np.dtype([("position", ">i2", (3,)), ("color", "u1", (4,))])
TRIANGLE_DTYPE: np.dtype = np.dtype([("flags", "u1"), ("indices", "u1", (3,)), ("uv", ">i2", (3, 2))])
BACKFACE_DRAW: int = 0x40
RENDER_HIDDEN: int = 0x100


class ModelError(AssetError):
    """A malformed model offset, count, batch range or vertex reference."""


def _readonly(array: NDArray[Scalar]) -> NDArray[Scalar]:
    result = np.ascontiguousarray(array)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class Bounds:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]

    def __post_init__(self) -> None:
        if any(a > b for a, b in zip(self.minimum, self.maximum)):
            raise ModelError("Bounding box minimum exceeds maximum")

    @classmethod
    def from_vertices(cls, vertices: FloatArray) -> Bounds:
        if len(vertices) == 0:
            raise ModelError("Cannot compute bounds of an empty model")
        lower, upper = vertices.min(axis=0), vertices.max(axis=0)
        return cls(tuple(float(v) for v in lower), tuple(float(v) for v in upper))


@dataclass(frozen=True)
class TextureInfo:
    texture_id: int
    width: int
    height: int
    format: int
    surface_type: int


@dataclass(frozen=True)
class TriangleBatchInfo:
    texture_index: int
    vertex_override: int
    vertices_offset: int
    faces_offset: int
    misc_data: int
    texture_offset: int
    flags: int

    @property
    def hidden(self) -> bool:
        return bool(self.flags & RENDER_HIDDEN)


@dataclass(frozen=True)
class BspNode:
    left_node: int
    right_node: int
    split_type: int
    segment_index: int
    split_value: int


@dataclass(frozen=True)
class LevelModelSegment:
    index: int
    vertices: FloatArray
    colors: ByteArray
    render_colors: ByteArray
    indices: IndexArray
    triangle_flags: ByteArray
    uvs: UVArray
    batches: tuple[TriangleBatchInfo, ...]
    terminal_batch: TriangleBatchInfo
    bounds: Bounds
    geometry_bounds: Bounds
    vertex_base: int
    face_base: int
    opaque_batch_count: int

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def triangle_count(self) -> int:
        return len(self.indices)


@dataclass(frozen=True)
class LevelModel:
    model_id: int
    segments: tuple[LevelModelSegment, ...]
    textures: tuple[TextureInfo, ...]
    bsp_nodes: tuple[BspNode, ...]
    stored_bounds: Bounds
    bounds: Bounds
    flat_vertices: FloatArray  # XYZ + normalized runtime RGBA, shape (N, 7).
    indices: IndexArray  # Global, zero-based vertex references, shape (T, 3).
    byte_size: int
    raw_data: bytes = b""  # Full inflated entry, including untouched tail/alignment.

    @property
    def vertex_count(self) -> int:
        return len(self.flat_vertices)

    @property
    def triangle_count(self) -> int:
        return len(self.indices)

    @classmethod
    def from_bytes(cls, data: bytes, *, model_id: int = 0) -> LevelModel:
        if len(data) < MODEL_HEADER_SIZE:
            raise ModelError("Truncated LevelModel header (requires 0x4C bytes)")
        size = struct.unpack_from(">i", data, 0x48)[0]
        if not MODEL_HEADER_SIZE <= size <= len(data):
            raise ModelError(f"Invalid modelSize {size} for {len(data)} decompressed bytes")

        def span(offset: int, count: int, stride: int, label: str) -> memoryview:
            if count < 0 or offset < 0 or offset > size or count * stride > size - offset:
                raise ModelError(f"{label} array extends outside modelSize")
            if count and offset < MODEL_HEADER_SIZE:
                raise ModelError(f"{label} array overlaps the model header")
            return memoryview(data)[offset:offset + count * stride]

        textures_ptr, segments_ptr, boxes_ptr, _, _, bsp_ptr = struct.unpack_from(">6I", data)
        texture_count, segment_count = struct.unpack_from(">2h", data, 0x18)
        if segment_count <= 0:
            raise ModelError("Model must contain at least one segment")
        textures = tuple(TextureInfo(*row) for row in struct.iter_unpack(
            ">IBBBb", span(textures_ptr, texture_count, 8, "TextureInfo")))
        span(segments_ptr, segment_count, SEGMENT_SIZE, "Segment")
        box_data = span(boxes_ptr, segment_count, 12, "Segment bounds")
        boxes = tuple(Bounds(tuple(float(v) for v in row[:3]), tuple(float(v) for v in row[3:]))
                      for row in struct.iter_unpack(">6h", box_data))
        header_box = struct.unpack_from(">6h", data, 0x3C)
        stored_bounds = Bounds((float(header_box[0]), float(header_box[2]), float(header_box[4])),
                               (float(header_box[1]), float(header_box[3]), float(header_box[5])))
        segments: list[LevelModelSegment] = []
        vertex_base = face_base = 0
        for index in range(segment_count):
            segment_offset = segments_ptr + index * SEGMENT_SIZE
            vertex_ptr, triangle_ptr, _, batch_ptr = struct.unpack_from(">4I", data, segment_offset)
            nv, nf, nb = struct.unpack_from(">3h", data, segment_offset + 0x1C)
            if nb < 0:
                raise ModelError(f"Segment {index}: negative batch count")
            vertices = np.frombuffer(span(vertex_ptr, nv, 10, f"Segment {index} vertices"), dtype=VERTEX_DTYPE)
            triangles = np.frombuffer(span(triangle_ptr, nf, 16, f"Segment {index} triangles"), dtype=TRIANGLE_DTYPE)
            all_batches = tuple(TriangleBatchInfo(*row) for row in BATCH_STRUCT.iter_unpack(
                span(batch_ptr, nb + 1, 12, f"Segment {index} batches + sentinel")))
            if (all_batches[0].vertices_offset, all_batches[0].faces_offset) != (0, 0):
                raise ModelError(f"Segment {index}: first batch must start at vertex/face zero")
            if (all_batches[-1].vertices_offset, all_batches[-1].faces_offset) != (nv, nf):
                raise ModelError(f"Segment {index}: terminal batch does not match vertex/triangle counts")
            indices = triangles["indices"].astype(np.uint32)
            for batch_index, (batch, following) in enumerate(zip(all_batches, all_batches[1:])):
                if not (0 <= batch.vertices_offset <= following.vertices_offset <= nv
                        and 0 <= batch.faces_offset <= following.faces_offset <= nf):
                    raise ModelError(f"Segment {index}, batch {batch_index}: invalid vertex/triangle range")
                if batch.texture_index != 0xFF and batch.texture_index >= texture_count:
                    raise ModelError(f"Segment {index}, batch {batch_index}: texture index outside TextureInfo array")
                faces = indices[batch.faces_offset:following.faces_offset]
                if faces.size and int(faces.max()) >= following.vertices_offset - batch.vertices_offset:
                    raise ModelError(f"Segment {index}, batch {batch_index}: triangle index outside its batch vertices")
                faces += batch.vertices_offset
            positions = _readonly(vertices["position"].astype(np.float32))
            colors = _readonly(vertices["color"].copy())
            display_colors = colors.copy()
            encoded_alpha = (colors[:, 0] == 1) & (colors[:, 1] == 1)
            display_colors[encoded_alpha, 3] = colors[encoded_alpha, 2]
            display_colors[encoded_alpha, :3] = 128
            segments.append(LevelModelSegment(
                index, positions, colors, _readonly(display_colors), _readonly(indices),
                _readonly(triangles["flags"].copy()), _readonly(triangles["uv"].astype(np.int16)),
                all_batches[:-1], all_batches[-1], boxes[index],
                Bounds.from_vertices(positions) if nv else boxes[index], vertex_base, face_base,
                data[segment_offset + 0x40],
            ))
            vertex_base += nv
            face_base += nf
        if vertex_base == 0:
            raise ModelError("Model contains no vertices")
        nodes = tuple(BspNode(*row) for row in struct.iter_unpack(
            ">hhBBh", span(bsp_ptr, segment_count - 1, 8, "BSP nodes")))
        _validate_bsp(nodes, segment_count)
        flat_vertices = _readonly(np.concatenate([
            np.column_stack((s.vertices, s.render_colors.astype(np.float32) / 255.0)) for s in segments
        ]))
        flat_indices = _readonly(np.concatenate([s.indices + s.vertex_base for s in segments]))
        return cls(model_id, tuple(segments), textures, nodes, stored_bounds,
                   Bounds.from_vertices(flat_vertices[:, :3]), flat_vertices, flat_indices, size, bytes(data))


def _validate_bsp(nodes: tuple[BspNode, ...], segment_count: int) -> None:
    for node in nodes:
        if node.split_type not in (0, 1, 2) or not 1 <= node.segment_index < segment_count:
            raise ModelError("Invalid BSP split axis or segment index")
        if any(child != -1 and not 0 <= child < len(nodes) for child in (node.left_node, node.right_node)):
            raise ModelError("BSP child index outside the node array")
    # Iterative DFS rejects cycles without risking Python recursion limits.
    completed: set[int] = set()
    for root in range(len(nodes)):
        pending = [(root, False)]
        active: set[int] = set()
        while pending:
            index, leaving = pending.pop()
            if index == -1 or index in completed:
                continue
            if leaving:
                active.remove(index)
                completed.add(index)
            else:
                if index in active:
                    raise ModelError("Cycle in BSP tree")
                active.add(index)
                node = nodes[index]
                pending.extend(((index, True), (node.right_node, False), (node.left_node, False)))


def load_level_model(source: RomImage | DecompAssets, model_id: int) -> LevelModel:
    """Read a Rare-compressed model entry (also the extractor's raw .bin format)."""
    return LevelModel.from_bytes(source.read_asset(AssetType.LEVEL_MODELS, model_id, decompress=True),
                                 model_id=model_id)
