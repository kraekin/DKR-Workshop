"""Geometry and OBJ invariants using synthetic buffers and the user's ROM."""

from __future__ import annotations

from pathlib import Path
import json
import struct
import zlib

import numpy as np
import pytest

from src.core.exporter import export_obj
from src.core.level_model import (
    BACKFACE_DRAW, RENDER_HIDDEN, TRIANGLE_DTYPE, VERTEX_DTYPE,
    LevelModel, ModelError, load_level_model,
)
from src.core.rom import AssetType, DecompAssets, RomImage

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def rom() -> RomImage:
    paths = list(ROOT.glob("*.z64"))
    if not paths:
        pytest.skip("Local USA Rev 1 ROM not present")
    return RomImage.from_file(paths[0])


def synthetic_model() -> bytes:
    """Two independent 3-vertex batches; second triangle uses local indexes 0..2."""
    data = bytearray(0x138)
    struct.pack_into(">6I", data, 0, 0x50, 0x58, 0x12C, 0, 0, 0x138)
    struct.pack_into(">2h", data, 0x18, 1, 1)
    struct.pack_into(">6h", data, 0x3C, 0, 10, 0, 5, 0, 10)
    struct.pack_into(">I", data, 0x48, len(data))
    struct.pack_into(">IBBBb", data, 0x50, 42, 32, 16, 1, -1)
    struct.pack_into(">4I", data, 0x58, 0xF0, 0xD0, 0, 0xA0)
    struct.pack_into(">3h", data, 0x58 + 0x1C, 6, 2, 2)
    struct.pack_into(">BbhhBBI", data, 0xA0, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into(">BbhhBBI", data, 0xAC, 255, -1, 3, 1, 0, 0, RENDER_HIDDEN)
    # Terminal metadata is deliberately garbage; only its two offsets are meaningful.
    struct.pack_into(">BbhhBBI", data, 0xB8, 99, -100, 6, 2, 127, 127, 0xFFFFFFFF)
    struct.pack_into(">BBBB6h", data, 0xD0, 0, 0, 1, 2, -32, 0, 0, -64, 32, 64)
    struct.pack_into(">BBBB6h", data, 0xE0, BACKFACE_DRAW, 0, 1, 2, 0, 0, 32, 0, 0, 32)
    vertices = [
        (0, 0, 0, 255, 0, 0, 255), (0, 0, 10, 0, 255, 0, 255), (10, 0, 0, 0, 0, 255, 255),
        (0, 5, 0, 1, 1, 64, 255), (10, 5, 0, 255, 255, 255, 255), (0, 5, 10, 255, 255, 255, 255),
    ]
    for index, vertex in enumerate(vertices):
        struct.pack_into(">hhhBBBB", data, 0xF0 + index * 10, *vertex)
    struct.pack_into(">6h", data, 0x12C, 0, 0, 0, 10, 5, 10)
    return bytes(data)


def test_synthetic_offsets_signed_uvs_and_loader_color_fixup() -> None:
    model = LevelModel.from_bytes(synthetic_model())
    assert VERTEX_DTYPE.itemsize == 10 and TRIANGLE_DTYPE.itemsize == 16
    assert (model.vertex_count, model.triangle_count, len(model.segments)) == (6, 2, 1)
    segment, = model.segments
    np.testing.assert_array_equal(segment.indices, [[0, 1, 2], [3, 4, 5]])
    assert segment.uvs[0].tolist() == [[-32, 0], [0, -64], [32, 64]]
    assert segment.colors[3].tolist() == [1, 1, 64, 255]
    assert segment.render_colors[3].tolist() == [128, 128, 128, 64]
    assert segment.batches[1].hidden and segment.triangle_flags[1] == BACKFACE_DRAW
    assert segment.terminal_batch.texture_index == 99  # Not validated as a real batch.
    assert model.textures[0].texture_id == 42 and model.textures[0].surface_type == -1
    assert model.bounds.minimum == (0.0, 0.0, 0.0) and model.bounds.maximum == (10.0, 5.0, 10.0)
    with pytest.raises(ValueError):
        model.flat_vertices[0, 0] = 999


@pytest.mark.parametrize("model_id,segments,vertices,triangles", [
    (0, 41, 4427, 3425), (5, 24, 1671, 1156), (16, 1, 26, 12), (54, 4, 2261, 1739),
])
def test_known_model_counts(rom: RomImage, model_id: int, segments: int, vertices: int, triangles: int) -> None:
    model = load_level_model(rom, model_id)
    assert (len(model.segments), model.vertex_count, model.triangle_count) == (segments, vertices, triangles)
    assert model.flat_vertices.shape == (vertices, 7) and model.indices.shape == (triangles, 3)
    assert len(model.bsp_nodes) == segments - 1


@pytest.mark.parametrize("model_id", range(55))
def test_every_rev1_model_has_valid_flattened_indices_and_bounds(rom: RomImage, model_id: int) -> None:
    model = load_level_model(rom, model_id)
    assert np.all(model.indices < model.vertex_count)
    assert model.flat_vertices.dtype == np.float32 and model.indices.dtype == np.uint32
    assert np.all((model.flat_vertices[:, 3:] >= 0) & (model.flat_vertices[:, 3:] <= 1))
    positions = model.flat_vertices[:, :3]
    np.testing.assert_array_equal(positions.min(axis=0), model.bounds.minimum)
    np.testing.assert_array_equal(positions.max(axis=0), model.bounds.maximum)
    for segment in model.segments:
        assert np.all(segment.indices < segment.vertex_count)
        start, end = segment.face_base, segment.face_base + segment.triangle_count
        np.testing.assert_array_equal(model.indices[start:end], segment.indices + segment.vertex_base)
        assert segment.terminal_batch.faces_offset == segment.triangle_count
        assert segment.terminal_batch.vertices_offset == segment.vertex_count


@pytest.mark.parametrize("offset,fmt,value", [
    (0x48, ">i", 0x139), (0x18, ">h", -1), (0x1A, ">h", -1),
    (0, ">I", 0xFFFFFFF0), (0x58, ">I", 0x137), (0x58 + 0x1C, ">h", -1),
    (0x58 + 0x20, ">h", -1), (0xA0, ">B", 1), (0xA2, ">h", 1),
    (0xAE, ">h", -1), (0xBA, ">h", 5), (0xBC, ">h", 1),
    (0xD1, ">B", 3), (0x132, ">h", -1),
])
def test_invalid_offsets_counts_batches_and_indices_fail(offset: int, fmt: str, value: int) -> None:
    data = bytearray(synthetic_model())
    struct.pack_into(fmt, data, offset, value)
    with pytest.raises(ModelError):
        LevelModel.from_bytes(bytes(data))


def test_truncated_header_and_missing_sentinel_fail() -> None:
    with pytest.raises(ModelError, match="header"):
        LevelModel.from_bytes(bytes(75))
    data = bytearray(synthetic_model())
    struct.pack_into(">I", data, 0x58 + 12, len(data) - 12)
    with pytest.raises(ModelError, match="sentinel"):
        LevelModel.from_bytes(bytes(data))


@pytest.mark.parametrize("relative,fmt,value", [(0, ">h", 0), (2, ">h", 999),
                                                (4, ">B", 3), (5, ">B", 255)])
def test_invalid_bsp_is_rejected(rom: RomImage, relative: int, fmt: str, value: int) -> None:
    data = bytearray(rom.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True))
    pointer = struct.unpack_from(">I", data, 0x14)[0]
    struct.pack_into(fmt, data, pointer + relative, value)
    with pytest.raises(ModelError, match="BSP"):
        LevelModel.from_bytes(bytes(data))


def read_obj(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, list[list[int]]]]:
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    groups: dict[str, list[list[int]]] = {}
    current = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "v":
            assert len(parts) == 7
            vertices.append([float(value) for value in parts[1:]])
        elif parts[0] == "g":
            current = parts[1]
            groups[current] = []
        elif parts[0] == "f":
            assert len(parts) == 4 and current
            face = [int(value) for value in parts[1:]]
            faces.append(face)
            groups[current].append(face)
    return np.asarray(vertices), np.asarray(faces), groups


def test_obj_includes_hidden_faces_and_correct_global_indexes(tmp_path: Path) -> None:
    model = LevelModel.from_bytes(synthetic_model())
    result = export_obj(model, tmp_path / "synthetic.obj")
    vertices, faces, groups = read_obj(result.path)
    assert (result.vertex_count, result.triangle_count, result.segment_count) == (6, 2, 1)
    assert list(groups) == ["segment_0"]
    np.testing.assert_array_equal(faces, [[1, 2, 3], [4, 5, 6]])
    np.testing.assert_allclose(vertices[:, :3], model.flat_vertices[:, :3] / 100)
    np.testing.assert_allclose(vertices[:, 3:], model.flat_vertices[:, 3:6], atol=1e-6)


@pytest.mark.parametrize("model_id", [0, 5])
def test_real_obj_has_all_named_segments_and_valid_faces(rom: RomImage, tmp_path: Path, model_id: int) -> None:
    model = load_level_model(rom, model_id)
    result = export_obj(model, tmp_path / f"model-{model_id}.obj")
    vertices, faces, groups = read_obj(result.path)
    assert len(vertices) == model.vertex_count and len(faces) == model.triangle_count
    assert list(groups) == [f"segment_{i}" for i in range(len(model.segments))]
    assert faces.min() >= 1 and faces.max() <= len(vertices)
    np.testing.assert_array_equal(faces - 1, model.indices)
    for segment in model.segments:
        assert len(groups[f"segment_{segment.index}"]) == segment.triangle_count


def test_failed_atomic_export_preserves_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "existing.obj"
    destination.write_text("keep", encoding="utf-8")

    def fail_replace(self: Path, target: Path) -> Path:
        raise PermissionError("test locked destination")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError):
        export_obj(LevelModel.from_bytes(synthetic_model()), destination)
    assert destination.read_text() == "keep" and not list(tmp_path.glob(".dkr-obj-*"))


def test_model_loads_from_decomp_raw_descriptor(tmp_path: Path) -> None:
    raw = synthetic_model()
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed = struct.pack("<IB", len(raw), 9) + compressor.compress(raw) + compressor.flush()
    (tmp_path / "track.bin").write_bytes(compressed)
    for filename, document in {
        "assets.meta.json": {"@dkr-version": "us.v80", "assets": {"sections": {
            "ASSET_LEVEL_MODELS": {"filename": "models.meta.json"}}}},
        "models.meta.json": {"folder": "", "files": {"order": ["MODEL_TEST"], "sections": {
            "MODEL_TEST": {"filename": "track.json"}}}},
        "track.json": {"type": "LevelModel", "raw": "track.bin"},
    }.items():
        (tmp_path / filename).write_text(json.dumps(document), encoding="utf-8")
    model = load_level_model(DecompAssets.from_directory(tmp_path), 0)
    assert model.vertex_count == 6 and model.triangle_count == 2
