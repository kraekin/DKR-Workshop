"""Headless OBJ/MTL/PNG export, including hidden geometry and UV seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile

from src.core.level_model import LevelModel, ModelError
from src.core.obj_units import GAME_UNITS_PER_OBJ_UNIT, OBJ_UNITS_PER_GAME_UNIT
from src.core.textures import Texture, model_uvs
from src.core.track_segments import collision_helper_faces


@dataclass(frozen=True)
class ExportResult:
    path: Path
    vertex_count: int
    triangle_count: int
    segment_count: int
    material_path: Path | None = None
    texture_paths: tuple[Path, ...] = ()


def export_obj(model: LevelModel, destination: Path | str,
               *, textures: Mapping[int, Texture] | None = None,
               helper_faces: frozenset[tuple[int,int]] | None = None) -> ExportResult:
    """Export world-space XYZ at 1:100 scale, RGB and optionally UVs/MTL/PNG.

    The UI always supplies textures. Omitting them retains the headless
    geometry-only API. Publish OBJ last; restore the prior MTL if it fails.
    Content-addressed PNG folders keep earlier exports intact during replacement.
    Texture animations are exported at each batch's serialized frame selection.
    """
    path = Path(destination).resolve()
    helpers = collision_helper_faces(model) if helper_faces is None else helper_faces
    triangle_count = model.triangle_count-len(helpers)
    if model.indices.size and int(model.indices.max()) >= model.vertex_count:
        raise ModelError("Cannot export out-of-bounds vertex indices")
    uv = model_uvs(model, textures, obj=True) if textures is not None else None
    keys: set[tuple[int, int]] = set()
    if textures is not None:
        for segment in model.segments:
            for batch in segment.batches:
                if (segment.index,batch.faces_offset) in helpers:
                    continue
                if batch.texture_index != 255:
                    texture_id = model.textures[batch.texture_index].texture_id
                    keys.add((texture_id, textures[texture_id].frame_index(batch.texture_offset)))
    # Sidecar names contain no spaces, so OBJ/MTL readers need no quote extension.
    prefix = re.sub(r"[^A-Za-z0-9_-]", "_", path.stem)[:80] or "track"
    mtl_stem = path.stem if re.fullmatch(r"[A-Za-z0-9_.-]+", path.stem) else prefix + "_" + hashlib.sha256(path.stem.encode()).hexdigest()[:8]
    material_path = path.parent / f"{mtl_stem}.mtl" if textures is not None else None
    digest = hashlib.sha256()
    for texture_id, frame_index in sorted(keys):
        assert textures is not None
        frame = textures[texture_id].frames[frame_index]
        digest.update(f"{texture_id}:{frame_index}:{frame.pixels.shape}".encode())
        digest.update(frame.pixels.tobytes())
    folder = path.parent / f"{prefix}_textures_{digest.hexdigest()[:16]}"
    published_pngs: list[Path] = []
    old_material = material_path.read_bytes() if material_path is not None and material_path.exists() else None
    material_published = False
    texture_paths: tuple[Path, ...] = ()
    # TemporaryDirectory owns only this call's generated staging directory.
    with tempfile.TemporaryDirectory(prefix=".dkr-obj-", dir=path.parent) as temporary:
        stage = Path(temporary)
        try:
            if textures is not None:
                materials = ["# DKR materials: PNG RGBA includes cutout alpha", "newmtl untextured", "Kd 1 1 1", "illum 0"]
                for texture_id, frame_index in sorted(keys):
                    frame = textures[texture_id].frames[frame_index]
                    name = f"texture_{texture_id}_frame_{frame_index}"
                    png = stage / f"{name}.png"
                    frame.to_image().save(png)
                    target = folder / png.name
                    # A transparent PNG carries both diffuse color and alpha.
                    materials.extend((f"\nnewmtl {name}", "Ka 1 1 1", "Kd 1 1 1", "Ks 0 0 0", "d 1", "illum 0",
                                      f"# clamp U={frame.header.clamp_u} V={frame.header.clamp_v}",
                                      f"map_Kd {folder.name}/{png.name}"))
                    if (frame.pixels[:, :, 3] < 255).any():
                        materials.append(f"map_d -imfchan a {folder.name}/{png.name}")
                # Use a safe MTL filename while keeping the conventional .mtl companion.
                mtl_name = material_path.name
                (stage / "materials.mtl").write_text("\n".join(materials) + "\n", encoding="utf-8")
            with (stage / "track.obj").open("w", encoding="utf-8", newline="\n") as stream:
                stream.write("# DKR track: compact world-space XYZ and normalized vertex RGB\n")
                stream.write(f"# 1 OBJ unit = {GAME_UNITS_PER_OBJ_UNIT:g} game units; Blender import/export Scale 1\n")
                stream.write(f"# Model {model.model_id}: {model.vertex_count} vertices, {triangle_count} triangles\n")
                if material_path is not None:
                    stream.write(f"mtllib {mtl_name}\n")
                for vertex in model.flat_vertices:
                    x, y, z, r, g, b = (float(value) for value in vertex[:6])
                    x, y, z = (value * OBJ_UNITS_PER_GAME_UNIT for value in (x, y, z))
                    stream.write(f"v {x:.9g} {y:.9g} {z:.9g} {r:.6f} {g:.6f} {b:.6f}\n")
                if uv is not None:
                    for u, v in uv.reshape(-1, 2):
                        stream.write(f"vt {u:.9g} {v:.9g}\n")
                stream.write("s off\n")
                for segment in model.segments:
                    stream.write(f"\ng segment_{segment.index}\n")
                    if textures is None:
                        for local,face in enumerate(segment.indices):
                            if (segment.index,local) in helpers:continue
                            stream.write("f " + " ".join(str(int(index) + segment.vertex_base + 1) for index in face) + "\n")
                    else:
                        batches = (*segment.batches, segment.terminal_batch)
                        for batch_index, (batch, following) in enumerate(zip(batches, batches[1:])):
                            if (segment.index,batch.faces_offset) in helpers:continue
                            material = "untextured"
                            if batch.texture_index != 255:
                                texture_id = model.textures[batch.texture_index].texture_id
                                frame_index = textures[texture_id].frame_index(batch.texture_offset)
                                material = f"texture_{texture_id}_frame_{frame_index}"
                            stream.write(f"usemtl {material}\n")
                            surface = model.textures[batch.texture_index].surface_type if batch.texture_index != 255 else None
                            stream.write(f"# DKR segment {segment.index} batch {batch_index} texture_slot {batch.texture_index} surface {surface} flags 0x{batch.flags:08X}\n")
                            for local in range(batch.faces_offset, following.faces_offset):
                                face = segment.indices[local]
                                first_uv = (segment.face_base + local) * 3 + 1
                                fields = [f"{int(index) + segment.vertex_base + 1}/{first_uv + corner}" for corner, index in enumerate(face)]
                                stream.write("f " + " ".join(fields) + "\n")
            if textures is not None:
                if keys:
                    folder.mkdir(exist_ok=True)
                for png in stage.glob("*.png"):
                    target = folder / png.name
                    if not target.exists():
                        png.replace(target)
                        published_pngs.append(target)
                    elif target.read_bytes() != png.read_bytes():
                        raise ModelError(f"Existing texture sidecar differs from its content hash: {target.name}")
                texture_paths = tuple(folder / f"texture_{tid}_frame_{frame}.png" for tid, frame in sorted(keys))
                (stage / "materials.mtl").replace(material_path)
                material_published = True
            (stage / "track.obj").replace(path)
        except Exception:
            if material_published and material_path is not None:
                if old_material is None:
                    material_path.unlink(missing_ok=True)
                else:
                    restore = stage / "restore.mtl"
                    restore.write_bytes(old_material)
                    os.replace(restore, material_path)
            for png in published_pngs:
                png.unlink(missing_ok=True)
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
            raise
    return ExportResult(path, model.vertex_count, triangle_count, len(model.segments), material_path, texture_paths)
