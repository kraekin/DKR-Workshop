"""Read-only Rev 1 ROM and decomp asset access, independent of Qt/OpenGL.

References: tools/dkr_assets_tool_extract.json, src/asset_loading.c,
extract/assetTable.cpp, extract/extractor.cpp and helpers/assetsHelper.cpp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from src.core.compression import decode_asset

REV1_SHA1: str = "6d96743d46f8c0cd0edb0ec5600b003c89b93755"
REV1_SIZE: int = 0xC00000
LUT_START: int = 0xED0E0
LUT_END: int = 0xED1B0
JsonObject = dict[str, Any]


class AssetError(ValueError):
    """Invalid ROM, manifest, index or asset span."""


class AssetType(IntEnum):
    AI_BEHAVIOUR = 0
    AI_BEHAVIOUR_TABLE = 1
    TEXTURES_3D = 2
    TEXTURES_3D_TABLE = 3
    TEXTURES_2D = 4
    TEXTURES_2D_TABLE = 5
    SPRITES = 12
    SPRITES_TABLE = 13
    EMPTY_14 = 14  # External CI palette bytes; empty in the original Rev 1 ROM.
    MENU_ELEMENT_IDS = 18  # Read-only packed menu references; menu.c:13787.
    LEVEL_OBJECT_MAPS_TABLE = 20
    LEVEL_OBJECT_MAPS = 21
    LEVEL_HEADERS_TABLE = 22
    LEVEL_HEADERS = 23
    LEVEL_NAMES_TABLE = 24
    LEVEL_NAMES = 25
    LEVEL_MODELS_TABLE = 26
    LEVEL_MODELS = 27
    OBJECT_MODELS_TABLE = 28
    OBJECT_MODELS = 29
    ANIMATION_IDS = 30
    OBJECT_ANIMATIONS_TABLE = 31
    OBJECT_ANIMATIONS = 32
    OBJECT_HEADERS_TABLE = 33
    OBJECTS = 34
    LEVEL_OBJECT_TRANSLATION_TABLE = 35
    AUDIO_TABLE = 38
    AUDIO = 39
    FONTS = 44  # Read-only Latin font metadata used to validate/display course names.


INDEX_TABLES: dict[AssetType, AssetType] = {
    AssetType.AI_BEHAVIOUR: AssetType.AI_BEHAVIOUR_TABLE,
    AssetType.TEXTURES_2D: AssetType.TEXTURES_2D_TABLE,
    AssetType.SPRITES: AssetType.SPRITES_TABLE,
    AssetType.TEXTURES_3D: AssetType.TEXTURES_3D_TABLE,
    AssetType.LEVEL_OBJECT_MAPS: AssetType.LEVEL_OBJECT_MAPS_TABLE,
    AssetType.LEVEL_HEADERS: AssetType.LEVEL_HEADERS_TABLE,
    AssetType.LEVEL_NAMES: AssetType.LEVEL_NAMES_TABLE,
    AssetType.LEVEL_MODELS: AssetType.LEVEL_MODELS_TABLE,
    AssetType.OBJECT_MODELS: AssetType.OBJECT_MODELS_TABLE,
    AssetType.OBJECT_ANIMATIONS: AssetType.OBJECT_ANIMATIONS_TABLE,
    AssetType.OBJECTS: AssetType.OBJECT_HEADERS_TABLE,
}


@dataclass(frozen=True)
class AssetSpan:
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


def normalize_rom(data: bytes) -> tuple[bytes, str]:
    """Detect the full N64 magic and normalize in memory; never rewrite a ROM."""
    if len(data) < 0x40:
        raise AssetError("ROM is shorter than the 64-byte N64 header")
    magic = data[:4]
    if magic == b"\x80\x37\x12\x40":
        return data, "z64"
    if magic == b"\x37\x80\x40\x12":
        word_size, order = 2, "v64"
    elif magic == b"\x40\x12\x37\x80":
        word_size, order = 4, "n64"
    else:
        raise AssetError(f"Unrecognized N64 ROM magic: {magic.hex().upper()}")
    if len(data) % word_size:
        raise AssetError(f"{order} ROM length is not a multiple of {word_size}")
    converted = bytearray(len(data))
    for byte in range(word_size):
        converted[byte::word_size] = data[word_size - 1 - byte::word_size]
    return bytes(converted), order


def parse_asset_lut(data: bytes, start: int, end: int) -> tuple[AssetSpan, ...]:
    """Resolve BE master offsets relative to LUT END, with complete bounds checks."""
    if start < 0 or end > len(data) or end - start < 12 or (end - start) % 4:
        raise AssetError("Invalid master asset table span")
    count = struct.unpack_from(">I", data, start)[0]
    if count < 1 or (count + 2) * 4 > end - start:
        raise AssetError("Master asset count exceeds the lookup table")
    offsets = struct.unpack_from(f">{count + 1}I", data, start + 4)
    if offsets[0] != 0 or any(a > b for a, b in zip(offsets, offsets[1:])):
        raise AssetError("Master asset offsets must start at zero and be ordered")
    if offsets[-1] > len(data) - end:
        raise AssetError("Master asset section extends beyond the ROM")
    return tuple(AssetSpan(end + a, end + b) for a, b in zip(offsets, offsets[1:]))


@dataclass(frozen=True)
class AssetTable:
    offsets: tuple[int, ...]

    @classmethod
    def parse(cls, data: bytes, data_size: int) -> AssetTable:
        if len(data) % 4 or data_size < 0:
            raise AssetError("Invalid asset index table size")
        offsets: list[int] = []
        for value, in struct.iter_unpack(">I", data):
            if value == 0xFFFFFFFF:
                break
            offsets.append(value)
        else:
            raise AssetError("Asset index table is missing its FFFFFFFF terminator")
        if not offsets or offsets[0] != 0:
            raise AssetError("Asset index table must start at zero")
        if any(a > b for a, b in zip(offsets, offsets[1:])) or offsets[-1] > data_size:
            raise AssetError("Asset index offsets are unordered or outside the data section")
        return cls(tuple(offsets))

    def __len__(self) -> int:
        return len(self.offsets) - 1

    def span(self, index: int) -> AssetSpan:
        if index < 0 or index >= len(self):
            raise AssetError(f"Asset index {index} outside 0..{len(self) - 1}")
        return AssetSpan(self.offsets[index], self.offsets[index + 1])


@dataclass(frozen=True)
class RomImage:
    data: bytes = field(repr=False)
    byte_order: str
    sections: tuple[AssetSpan, ...]
    source_path: Path | None = None

    @classmethod
    def from_bytes(cls, data: bytes, *, source_path: Path | None = None) -> RomImage:
        normalized, order = normalize_rom(data)
        digest = hashlib.sha1(normalized).hexdigest()
        if len(normalized) != REV1_SIZE or digest != REV1_SHA1:
            raise AssetError(
                "Unsupported or modified ROM. Expected Diddy Kong Racing USA Rev 1 "
                f"(us.v80, SHA-1 {REV1_SHA1}); received SHA-1 {digest}."
            )
        sections = parse_asset_lut(normalized, LUT_START, LUT_END)
        if len(sections) != 50:
            raise AssetError("Rev 1 must contain 50 master asset sections")
        return cls(normalized, order, sections, source_path)

    @classmethod
    def from_file(cls, path: Path | str) -> RomImage:
        source = Path(path).resolve()
        if source.stat().st_size != REV1_SIZE:
            raise AssetError(f"Expected a {REV1_SIZE}-byte USA Rev 1 ROM")
        return cls.from_bytes(source.read_bytes(), source_path=source)

    @property
    def description(self) -> str:
        name = self.source_path.name if self.source_path else "ROM in memory"
        return f"{name} · USA Rev 1 / us.v80 · {self.byte_order}"

    def section(self, asset_type: AssetType) -> bytes:
        index = int(asset_type)
        if index < 0 or index >= len(self.sections):
            raise AssetError(f"Master asset index {index} is out of bounds")
        span = self.sections[index]
        return self.data[span.start:span.end]

    def index_table(self, asset_type: AssetType) -> AssetTable:
        try:
            table_type = INDEX_TABLES[asset_type]
        except KeyError as error:
            raise AssetError(f"No supported index table for {asset_type.name}") from error
        return AssetTable.parse(self.section(table_type), len(self.section(asset_type)))

    def count(self, asset_type: AssetType) -> int:
        return len(self.index_table(asset_type))

    def read_asset(self, asset_type: AssetType, index: int, *, decompress: bool = False) -> bytes:
        span = self.index_table(asset_type).span(index)
        if span.size == 0:
            return b""  # Duplicate offsets denote a vacant slot, not a gzip stream.
        data = self.section(asset_type)[span.start:span.end]
        return decode_asset(data, compressed=decompress)


def read_json(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AssetError(f"Invalid JSON in {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise AssetError(f"Expected a JSON object in {path.name}")
    return value


@dataclass
class DecompAssets:
    """Read the extractor's assets.meta.json and section files without generating assets."""

    root: Path
    manifest: JsonObject = field(repr=False)
    _sections: dict[AssetType, JsonObject] = field(default_factory=dict, repr=False)

    @classmethod
    def from_directory(cls, directory: Path | str) -> DecompAssets:
        chosen = Path(directory).resolve()
        candidates = (chosen, chosen / "assets", chosen / "assets/.vanilla/us.v80",
                      chosen / ".vanilla/us.v80")
        for root in candidates:
            path = root / "assets.meta.json"
            if path.is_file():
                manifest = read_json(path)
                if manifest.get("@dkr-version") != "us.v80":
                    raise AssetError("Extracted assets must be tagged @dkr-version = us.v80 (USA Rev 1)")
                return cls(root, manifest)
        raise AssetError(
            "No extracted us.v80 assets.meta.json found. Choose the decomp root, "
            "assets directory, or assets/.vanilla/us.v80. For a source-only checkout, use Open ROM."
        )

    @property
    def description(self) -> str:
        return f"{self.root} · extracted us.v80 assets"

    def _path(self, base: Path, relative: str) -> Path:
        if not isinstance(relative, str) or not relative:
            raise AssetError("Missing asset filename in manifest")
        path = (base / relative).resolve()
        if not path.is_relative_to(self.root):
            raise AssetError("Manifest filename points outside the selected asset directory")
        return path

    def section_manifest(self, asset_type: AssetType) -> JsonObject:
        if asset_type not in self._sections:
            try:
                info = self.manifest["assets"]["sections"][f"ASSET_{asset_type.name}"]
                path = self._path(self.root, info["filename"])
            except (KeyError, TypeError) as error:
                raise AssetError(f"Missing section manifest for ASSET_{asset_type.name}") from error
            self._sections[asset_type] = read_json(path)
        return self._sections[asset_type]

    def order(self, asset_type: AssetType) -> tuple[str, ...]:
        section = self.section_manifest(asset_type)
        if "filename" in section and "files" not in section:
            return (f"ASSET_{asset_type.name}",)
        try:
            order = section["files"]["order"]
        except (KeyError, TypeError) as error:
            raise AssetError(f"Missing files/order for ASSET_{asset_type.name}") from error
        if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
            raise AssetError("Manifest files/order must be an array of build IDs")
        if len(set(order)) != len(order):
            raise AssetError("Duplicate build IDs in manifest order")
        return tuple(order)

    def count(self, asset_type: AssetType) -> int:
        return len(self.order(asset_type))

    def resolve_id(self, asset_type: AssetType, build_id: str | int) -> int:
        order = self.order(asset_type)
        if isinstance(build_id, str):
            try:
                return order.index(build_id)
            except ValueError as error:
                raise AssetError(f"Unknown ASSET_{asset_type.name} build ID: {build_id}") from error
        if type(build_id) is not int or build_id < -1 or build_id >= len(order):
            raise AssetError(f"Invalid ASSET_{asset_type.name} ID: {build_id}")
        return build_id

    def entry_path(self, asset_type: AssetType, index: int) -> Path:
        order = self.order(asset_type)
        if index < 0 or index >= len(order):
            raise AssetError(f"Asset index {index} outside ASSET_{asset_type.name}")
        section = self.section_manifest(asset_type)
        if "filename" in section and "files" not in section:
            return self._path(self.root / section.get("folder", ""), section["filename"])
        try:
            folder = section.get("folder", "")
            filename = section["files"]["sections"][order[index]]["filename"]
            base = self.root / folder
        except (KeyError, TypeError) as error:
            raise AssetError(f"Missing filename for {order[index]}") from error
        return self._path(base, filename)

    def read_asset(self, asset_type: AssetType, index: int, *, decompress: bool = False) -> bytes:
        path = self.entry_path(asset_type, index)
        if path.suffix.casefold() == ".json":
            metadata = read_json(path)
            if "raw" not in metadata:
                raise AssetError(f"{path.name} is structured JSON, not a raw binary asset")
            path = self._path(path.parent, metadata["raw"])
        return decode_asset(path.read_bytes(), compressed=decompress)
