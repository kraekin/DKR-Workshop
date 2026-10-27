"""Level catalog from Rev 1 tables or the local decomp extractor's manifests.

Binary offsets: include/structs.h and src/game.c. JSON field names/defaults:
extractLevelHeader.cpp and buildLevelHeader.cpp. Text: text/dkrText.cpp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct
from typing import Any

from src.core.rom import AssetError, AssetType, DecompAssets, JsonObject, RomImage, read_json

RGB = tuple[int, int, int]
AILevels = tuple[int, int, int, int, int]
LANGUAGES: tuple[str, ...] = ("ENGLISH", "GERMAN", "FRENCH", "JAPANESE")
WORLD_SYMBOLS: tuple[str, ...] = (
    "WORLD_NONE", "WORLD_CENTRAL_AREA", "WORLD_DINO_DOMAIN", "WORLD_SHERBET_ISLAND",
    "WORLD_SNOWFLAKE_MOUNTAIN", "WORLD_DRAGON_FOREST", "WORLD_FUTURE_FUN_LAND",
)
WORLD_NAMES: tuple[str, ...] = (
    "None", "Central Area", "Dino Domain", "Sherbet Island", "Snowflake Mountain",
    "Dragon Forest", "Future Fun Land",
)
RACE_TYPES: dict[str, int] = {
    "RACETYPE_DEFAULT": 0, "RACETYPE_UNK1": 1, "RACETYPE_HORSESHOE_GULCH": 3,
    "RACETYPE_HUBWORLD": 5, "RACETYPE_CUTSCENE_1": 6, "RACETYPE_CUTSCENE_2": 7,
    "RACETYPE_BOSS": 8, "RACETYPE_CHALLENGE_BATTLE": 64,
    "RACETYPE_CHALLENGE_BANANAS": 65, "RACETYPE_CHALLENGE_EGGS": 66,
}
VEHICLES: dict[str, int] = {"VEHICLE_CAR": 0, "VEHICLE_HOVERCRAFT": 1, "VEHICLE_PLANE": 2}

# The 256-character index map from tools/dkr_assets_tool_src/text/dkrText.cpp.
# These are encoding definitions, not ROM-extracted font images or glyph data.
JP_CHARACTERS: tuple[str, ...] = ("",) + tuple(
    "、$()・%「」’”<>&〜 "
    "0123456789ABCDEF"
    "GHIJKLMNOPQRSTUV"
    "WXYZ!\"#'*+,-./:="
    "?@。゛゜ァィゥェォッャュョヲン"
    "アイウエオカキクケコサシスセソタ"
    "チツテトナニヌネノハヒフヘホマミ"
    "ムメモヤユヨラリルレロワガギグゲ"
    "ゴザジズゼゾダヂヅデドバビブベボ"
    "パピプペポabcdefghijk"
    "lmnopqrstuvwxyzぁ"
    "ぃぅぇぉっゃゅょをんあいうえおか"
    "きくけこさしすせそたちつてとなに"
    "ぬねのはひふへほまみむめもやゆよ"
    "らりるれろわがぎぐげござじずぜぞ"
    "だぢづでどばびぶべぼぱぴぷぺぽヴ"
)


@dataclass(frozen=True)
class LevelNames:
    english: str
    german: str = ""
    french: str = ""
    japanese: str = ""

    @classmethod
    def from_bytes(cls, data: bytes) -> LevelNames:
        names: list[str] = []
        offset = 0
        for language in LANGUAGES:
            characters: list[str] = []
            while True:
                if offset >= len(data):
                    raise AssetError(f"Unterminated {language.lower()} level name")
                value = data[offset]
                offset += 1
                if value == 0:
                    break
                if value & 0x80:
                    if offset >= len(data):
                        raise AssetError("Truncated two-byte DKRJP character")
                    glyph = ((value & 0x7F) << 8) | data[offset]
                    offset += 1
                    if glyph >= len(JP_CHARACTERS):
                        raise AssetError(f"Unknown DKRJP character index {glyph}")
                    characters.append(JP_CHARACTERS[glyph])
                else:
                    characters.append(chr(value))
            names.append("".join(characters))
        return cls(*names)

    @classmethod
    def from_json(cls, value: JsonObject) -> LevelNames:
        if not isinstance(value, dict):
            raise AssetError("Expected a level name language object")
        names = [value.get(f"LANGUAGE_{language}", "") for language in LANGUAGES]
        if not all(isinstance(name, str) for name in names):
            raise AssetError("Level names must be strings")
        return cls(*names)


def _get(document: JsonObject, path: str, default: Any = None) -> Any:
    value: Any = document
    for key in path.split("/"):
        if isinstance(value, list) and key.isdigit():
            if int(key) >= len(value):
                return default
            value = value[int(key)]
            continue
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _integer(document: JsonObject, path: str, default: int | None = None) -> int:
    value = _get(document, path, default)
    if type(value) is not int:
        raise AssetError(f"{path} must be an integer")
    return value


def _enum(value: Any, symbols: dict[str, int], label: str) -> int:
    if type(value) is int and value in symbols.values():
        return value
    if isinstance(value, str) and value in symbols:
        return symbols[value]
    raise AssetError(f"Unknown {label}: {value}")


def _rgb(document: JsonObject, path: str) -> RGB:
    return (_integer(document, f"{path}/red"), _integer(document, f"{path}/green"),
            _integer(document, f"{path}/blue"))


@dataclass(frozen=True)
class FogSettings:
    near: int
    far: int
    color: RGB


@dataclass(frozen=True)
class LevelHeader:
    geometry_id: int
    object_map_id: int
    secondary_object_map_id: int
    skybox_id: int
    world: int
    race_type: int
    vehicle: int
    available_vehicles: int
    laps: int
    camera_fov: int
    course_height: float
    fog: FogSettings
    background_color: RGB
    background_bottom: RGB
    background_top: RGB
    special_sky: int
    special_sky_texture: int
    ai_adv1: AILevels
    ai_adv2: AILevels
    raw_data: bytes | None = field(default=None, repr=False)
    checkpoint_sets: tuple[int, int, int] = (0, 0, 0)

    @classmethod
    def from_bytes(cls, data: bytes) -> LevelHeader:
        if len(data) not in (0xC4, 0xC8):
            raise AssetError(f"Level header must be 0xC4 runtime or 0xC8 serialized bytes; got {len(data)}")
        geometry, objects, skybox = struct.unpack_from(">3h", data, 0x34)
        near, far, red, green, blue = struct.unpack_from(">5h", data, 0x3A)
        height = struct.unpack_from(">f", data, 8)[0]
        if not math.isfinite(height):
            raise AssetError("Level course height is not finite")
        return cls(
            geometry_id=geometry, object_map_id=objects,
            secondary_object_map_id=struct.unpack_from(">h", data, 0xBA)[0], skybox_id=skybox,
            world=struct.unpack_from(">b", data, 0)[0], race_type=struct.unpack_from(">b", data, 0x4C)[0],
            vehicle=struct.unpack_from(">b", data, 0x4D)[0], available_vehicles=data[0x4E],
            laps=struct.unpack_from(">b", data, 0x4B)[0], camera_fov=struct.unpack_from(">b", data, 0x9C)[0],
            course_height=height, fog=FogSettings(near, far, (red, green, blue)),
            background_color=struct.unpack_from(">3B", data, 0x9D),
            background_bottom=struct.unpack_from(">3B", data, 0xBE),
            background_top=struct.unpack_from(">3B", data, 0xC1),
            special_sky=struct.unpack_from(">b", data, 0x49)[0],
            special_sky_texture=struct.unpack_from(">I", data, 0xA4)[0],
            ai_adv1=struct.unpack_from(">5b", data, 0x20), ai_adv2=struct.unpack_from(">5b", data, 0x25),
            raw_data=data,
            checkpoint_sets=struct.unpack_from(">3b", data, 0x4F),
        )

    @classmethod
    def from_json(cls, document: JsonObject, assets: DecompAssets) -> LevelHeader:
        if document.get("type") != "LevelHeader":
            raise AssetError("Expected a LevelHeader JSON document")
        height = _get(document, "course-height", 0)
        try:
            valid_height = type(height) in (int, float) and math.isfinite(height)
        except OverflowError:
            valid_height = False
        if not valid_height:
            raise AssetError("course-height must be finite")
        available = document.get("avaliable-vehicles", [])  # Exact spelling in the local extractor.
        if not isinstance(available, list):
            raise AssetError("avaliable-vehicles must be an array")
        vehicle_mask = 0
        for vehicle in available:
            vehicle_mask |= 1 << _enum(vehicle, VEHICLES, "vehicle")
        ai: list[AILevels] = []
        for adventure in ("adv1", "adv2"):
            values = tuple(_integer(document, f"ai-levels/{adventure}/{key}", 0)
                           for key in ("base", "silver-coins", "completed", "tracks-mode", "trophy-race"))
            ai.append((values[0], values[1], values[2], values[3], values[4]))
        return cls(
            geometry_id=assets.resolve_id(AssetType.LEVEL_MODELS, document.get("model")),
            object_map_id=assets.resolve_id(AssetType.LEVEL_OBJECT_MAPS, document.get("map-collectables")),
            secondary_object_map_id=assets.resolve_id(AssetType.LEVEL_OBJECT_MAPS, document.get("map-2")),
            skybox_id=assets.resolve_id(AssetType.OBJECTS, _get(document, "background/skybox/id", -1)),
            world=_enum(document.get("world"), {name: i - 1 for i, name in enumerate(WORLD_SYMBOLS)}, "world"),
            race_type=_enum(document.get("race-type"), RACE_TYPES, "race type"),
            vehicle=_enum(document.get("default-vehicle", "VEHICLE_CAR"), VEHICLES, "vehicle"),
            available_vehicles=vehicle_mask, laps=_integer(document, "lap-count", 3),
            camera_fov=_integer(document, "fov", 60), course_height=float(height),
            fog=FogSettings(_integer(document, "fog/near"), _integer(document, "fog/far"),
                            _rgb(document, "fog/colour")),
            background_color=_rgb(document, "background/colour"),
            background_bottom=_rgb(document, "background/multiplayer/gradient-colour/bottom"),
            background_top=_rgb(document, "background/multiplayer/gradient-colour/top"),
            special_sky=_integer(document, "background/skybox/special-sky", 0),
            special_sky_texture=_integer(document, "background/skybox/special-sky-texture", 0),
            ai_adv1=ai[0], ai_adv2=ai[1],
            checkpoint_sets=tuple(_integer(document, f"unknown/unk4F/{i}", 0) for i in range(3)),
        )

    @property
    def world_name(self) -> str:
        return WORLD_NAMES[self.world + 1] if -1 <= self.world < 6 else f"World {self.world}"

    @property
    def category(self) -> str:
        if self.world < 0 or self.race_type in (6, 7):
            return "Cutscene / Menu"
        if self.race_type == 5:
            return "Hub"
        if self.race_type == 8:
            return "Boss"
        if self.race_type & 0x40:
            return "Challenge"
        return "Track" if self.race_type == 0 else "Other"


@dataclass(frozen=True)
class LevelEntry:
    index: int
    names: LevelNames
    header: LevelHeader
    build_id: str | None = None

    @property
    def name(self) -> str:
        return self.names.english or f"Level {self.index}"


@dataclass(frozen=True)
class LevelCatalog:
    source: RomImage | DecompAssets
    levels: tuple[LevelEntry, ...]


def load_level_catalog(source: RomImage | DecompAssets) -> LevelCatalog:
    """Load every header without filtering out hubs, arenas or cinematic stages."""
    count = source.count(AssetType.LEVEL_HEADERS)
    if count == 0:
        raise AssetError("Level catalog is empty")
    if isinstance(source, RomImage) and source.count(AssetType.LEVEL_NAMES) != count:
        raise AssetError("Level header and name table counts differ")
    model_count = source.count(AssetType.LEVEL_MODELS)
    map_count = source.count(AssetType.LEVEL_OBJECT_MAPS)
    object_count = source.count(AssetType.OBJECTS)
    levels: list[LevelEntry] = []
    for index in range(count):
        build_id: str | None = None
        document: JsonObject | None = None
        if isinstance(source, DecompAssets):
            build_id = source.order(AssetType.LEVEL_HEADERS)[index]
            path = source.entry_path(AssetType.LEVEL_HEADERS, index)
            if path.suffix.casefold() == ".json":
                document = read_json(path)
        try:
            if document is not None and document.get("type") == "LevelHeader" and "raw" not in document:
                header = LevelHeader.from_json(document, source)
                names_value = document.get("name")
                if not isinstance(names_value, dict):
                    raise AssetError("Missing name language object")
                names = LevelNames.from_json(names_value)
            else:
                header = LevelHeader.from_bytes(source.read_asset(AssetType.LEVEL_HEADERS, index))
                if isinstance(source, DecompAssets):
                    name_path = source.entry_path(AssetType.LEVEL_NAMES, index)
                    name_document = read_json(name_path) if name_path.suffix.casefold() == ".json" else None
                    if name_document is not None and name_document.get("type") == "LevelName":
                        names = LevelNames.from_json(name_document.get("languages", {}))
                    else:
                        names = LevelNames.from_bytes(source.read_asset(AssetType.LEVEL_NAMES, index))
                else:
                    names = LevelNames.from_bytes(source.read_asset(AssetType.LEVEL_NAMES, index))
            if not 0 <= header.geometry_id < model_count:
                raise AssetError(f"Geometry ID {header.geometry_id} outside model table")
            for value in (header.object_map_id, header.secondary_object_map_id):
                if value < -1 or value >= map_count:
                    raise AssetError(f"Object map ID {value} outside map table")
            if header.skybox_id < -1 or header.skybox_id >= object_count:
                raise AssetError(f"Skybox ID {header.skybox_id} outside object header table")
        except (ValueError, OSError) as error:
            raise AssetError(f"Level {index}: {error}") from error
        levels.append(LevelEntry(index, names, header, build_id))
    return LevelCatalog(source, tuple(levels))
