"""Manifest-based fixed-layout PNG exchange; all imports stage before one Apply."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING

import numpy as np

from src.core.image_assets import (export_png, read_png, png_flip_default, png_rows,
    sprite_canvas, split_sprite_png, replace_frame, texture_from_raw, TEXTURE_SECTIONS)
from src.core.rom import AssetType, REV1_SHA1
from src.core.textures import load_sprite

if TYPE_CHECKING:
    from src.core.editing import EditSession

ImageKey = tuple[AssetType, int]
MAX_FRAMES = 16384
MAX_PIXELS = 32 * 1024 * 1024


@dataclass(frozen=True)
class BatchImagePlan:
    changes: tuple[tuple[ImageKey, bytes, bytes], ...]
    report: tuple[str, ...]
    uses: tuple[str, ...]


def image_frames(session: EditSession, key: ImageKey) -> tuple[np.ndarray, ...]:
    section, index = key
    if section == AssetType.SPRITES:
        sprite = load_sprite(session.asset_source, index)
        return tuple(sprite_canvas(session.asset_source, index, frame).pixels
                     for frame in range(sprite.frame_count) if sprite.texture_ids(frame))
    if section not in TEXTURE_SECTIONS:
        raise ValueError("Choose 2D textures, 3D textures or sprites")
    return tuple(frame.pixels for frame in session.image_texture(*key).frames)


def changed_image(session: EditSession, key: ImageKey) -> bool:
    if key[0] == AssetType.TEXTURES_3D and key[1] >= session.rom.count(AssetType.TEXTURES_3D):
        return True  # Appended custom artwork is new relative to the original ROM.
    if session.current_asset(*key) != session.original_asset(*key):
        return True
    if key[0] == AssetType.SPRITES:
        return any(session.current_asset(AssetType.TEXTURES_2D, index) != session.original_asset(AssetType.TEXTURES_2D, index)
                   for frame in range(load_sprite(session.asset_source, key[1]).frame_count)
                   for index in load_sprite(session.asset_source, key[1]).texture_ids(frame))
    return False


def export_image_batch(session: EditSession, keys: tuple[ImageKey, ...], destination: Path,
                       *, sheets: bool = False) -> Path:
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("Select distinct image assets to export")
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Choose a new package folder; existing files will not be overwritten")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".dkr-images-", dir=destination.parent))
    entries: list[dict[str, object]] = []
    total_frames = total_pixels = 0
    try:
        for key in keys:
            section, index = key
            frames = image_frames(session, key)
            # Empty sprite frames retain their real indexes instead of shifting.
            numbers = tuple(frame for frame in range(load_sprite(session.asset_source, index).frame_count)
                            if load_sprite(session.asset_source, index).texture_ids(frame)) if section == AssetType.SPRITES else tuple(range(len(frames)))
            if not frames:
                raise ValueError(f"{section.name} {index} has no nonempty frames")
            total_frames += len(frames)
            total_pixels += sum(frame.shape[0] * frame.shape[1] for frame in frames)
            if total_frames > MAX_FRAMES or total_pixels > MAX_PIXELS:
                raise ValueError("Batch is too large; export a smaller selection")
            flip = png_flip_default(session.asset_source, section, index)
            name = f"{section.name.lower()}_{index:04d}"
            sheet = None
            if sheets:
                sheet = np.zeros((max(p.shape[0] for p in frames), sum(p.shape[1] for p in frames), 4), np.uint8)
                if sheet.shape[0] * sheet.shape[1] > MAX_PIXELS:
                    raise ValueError("Animation sheet is too large; export separate frames")
            cursor = 0
            for number, pixels in zip(numbers, frames):
                height, width = pixels.shape[:2]
                filename = f"{name}.png" if sheets else f"{name}_frame_{number:03d}.png"
                entry = dict(section=int(section), index=index, frame=number, file=filename,
                             width=width, height=height, flip_y=flip, x=cursor if sheets else 0, y=0,
                             pixels_sha256=hashlib.sha256(pixels.tobytes()).hexdigest())
                entries.append(entry)
                if sheets:
                    sheet[:height, cursor:cursor + width] = png_rows(pixels, flip_y=flip)
                else:
                    export_png(pixels, temporary / filename, asset_type=section, flip_y=flip)
                cursor += width
            if sheets:
                # Frames are independently oriented above; the sheet is raw rows.
                export_png(sheet, temporary / f"{name}.png")
        document = dict(format="dkr-image-batch", version=1, rom_sha1=REV1_SHA1,
                        layout="sheets" if sheets else "frames", entries=entries)
        (temporary / "images.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        temporary.rename(destination)
    finally:
        if temporary.exists():
            if temporary.resolve().parent != destination.parent or not temporary.name.startswith(".dkr-images-"):
                raise ValueError("Unexpected staging directory; refusing cleanup")
            shutil.rmtree(temporary)
    return destination / "images.json"


def stage_image_batch(session: EditSession, manifest: Path) -> BatchImagePlan:
    if manifest.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Image manifest is too large")
    document = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if (not isinstance(document, dict) or document.get("format") != "dkr-image-batch"
            or document.get("version") != 1 or document.get("rom_sha1") != REV1_SHA1
            or document.get("layout") not in ("frames", "sheets")):
        raise ValueError("Choose a supported Workshop image manifest for the original USA Rev 1 ROM")
    entries = document.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FRAMES:
        raise ValueError("Invalid batch frame count")
    root = manifest.parent.resolve()
    seen: set[tuple[AssetType, int, int]] = set()
    targets: dict[tuple[ImageKey, int], np.ndarray] = {}
    reports: list[str] = []
    originals: dict[ImageKey, bytes] = {}
    total = 0
    for entry in entries:
        if (not isinstance(entry, dict) or any(type(entry.get(name)) is not int for name in ("section", "index", "frame", "width", "height", "x", "y"))
                or type(entry.get("flip_y")) is not bool or not isinstance(entry.get("file"), str)
                or entry["width"] < 1 or entry["height"] < 1 or entry["x"] < 0 or entry["y"] < 0):
            raise ValueError("Invalid batch frame fields")
    for entry in entries:
        if not isinstance(entry, dict) or any(type(entry.get(name)) is not int for name in ("section", "index", "frame", "width", "height", "x", "y")) or type(entry.get("flip_y")) is not bool:
            raise ValueError("Invalid batch frame fields")
        section, index, frame = AssetType(entry["section"]), entry["index"], entry["frame"]
        if section not in (*TEXTURE_SECTIONS, AssetType.SPRITES) or index < 0 or frame < 0:
            raise ValueError("Invalid image identity")
        if (section, index, frame) in seen:
            raise ValueError("Duplicate image frame in manifest")
        seen.add((section, index, frame))
        if section == AssetType.SPRITES:
            canvas = sprite_canvas(session.asset_source, index, frame)
            current = canvas.pixels
        else:
            texture = session.image_texture(section, index)
            if frame >= len(texture.frames):
                raise ValueError("Frame index exceeds existing animation")
            current = texture.frames[frame].pixels
        height, width = current.shape[:2]
        total += height * width
        if total > MAX_PIXELS or (entry["width"], entry["height"]) != (width, height):
            raise ValueError("Batch dimensions changed or package is too large")
        if entry.get("pixels_sha256") != hashlib.sha256(current.tobytes()).hexdigest():
            raise ValueError(f"{section.name} {index} frame {frame} changed since export; export a fresh package")
        if not isinstance(entry.get("file"), str):
            raise ValueError("Invalid image filename")
        path = (root / entry["file"]).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Image paths must stay inside the package folder")
        if document["layout"] == "sheets":
            from PIL import Image
            with Image.open(path) as image:
                x, y = entry["x"], entry["y"]
                same_file = [e for e in entries if e["file"] == entry["file"]]
                expected = (max(e["x"] + e["width"] for e in same_file), max(e["y"] + e["height"] for e in same_file))
                if image.format != "PNG" or getattr(image, "n_frames", 1) != 1 or image.width * image.height > MAX_PIXELS or image.size != expected:
                    raise ValueError("Invalid animation sheet bounds")
                pixels = png_rows(np.array(image.crop((x, y, x + width, y + height)).convert("RGBA"), np.uint8), flip_y=entry["flip_y"])
        else:
            pixels = read_png(path, (width, height), asset_type=section, flip_y=entry["flip_y"])
        if np.array_equal(pixels, current):
            continue  # Keep unedited frames byte-identical, even CI quantization ties.
        pieces = split_sprite_png(canvas, pixels) if section == AssetType.SPRITES else {index: pixels}
        for tile, pixel in pieces.items():
            key, number = ((AssetType.TEXTURES_2D, tile), 0) if section == AssetType.SPRITES else ((section, tile), frame)
            if (key, number) in targets and not np.array_equal(targets[key, number], pixel):
                raise ValueError(f"Conflicting imported pixels for shared texture {key[1]} frame {number}")
            targets[key, number] = pixel
            originals.setdefault(key, session.current_asset(*key))
        reports.append(f"{section.name} {index} frame {frame}: {np.count_nonzero(np.any(pixels != current, axis=2))} changed pixels")
    updates = dict(originals)
    for (key, frame), pixels in targets.items():
        updates[key] = replace_frame(updates[key], frame, pixels, palettes=session.rom.section(AssetType.EMPTY_14))
        decoded = texture_from_raw(updates[key], key[1], session.rom.section(AssetType.EMPTY_14)).frames[frame].pixels
        error = int(np.max(np.abs(decoded.astype(np.int16) - pixels.astype(np.int16))))
        reports.append(f"Stored {key[0].name} {key[1]} frame {frame}: maximum channel quantization error {error}/255")
    for key, raw in updates.items():
        session._validate_asset(key, raw)
    uses = set()
    for key in updates:
        uses.update(session.image_uses.direct.get(key, ()))
        uses.update(session.image_uses.levels.get(key, ()))
    return BatchImagePlan(tuple((key, originals[key], raw) for key, raw in sorted(updates.items())),
                          tuple(reports), tuple(sorted(uses)))


def apply_image_batch(session: EditSession, plan: BatchImagePlan) -> bool:
    if any(session.current_asset(*key) != before for key, before, _ in plan.changes):
        raise ValueError("Image assets changed after preview; review the package again")
    return session._replace_assets({key: after for key, _, after in plan.changes}, "Import image batch")
