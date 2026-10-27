"""Verified fixed LevelHeader editing metadata and validation, without Qt/GL.

Local sources: structs.h:LevelHeader; tools/fileTypes/levelHeader.hpp;
game.c:load_level/aitable_init/level_music_start; camera.c:cam_set_fov;
tracks.c:set_fog/skydome_spawn; weather.c:weather_reset; audio.c:audio_init.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from src.core.level_header import LevelCatalog, LevelHeader
from src.core.objects import ObjectDatabase
from src.core.rom import AssetError, AssetType, RomImage

SettingValue = int | tuple[int, ...]
Choices = tuple[tuple[int, str], ...]

# Names from local include/sequence_ids.h, in its implicit enum order.
SEQUENCE_NAMES: tuple[str, ...] = (
    "None", "None 2", "Amulet Theme", "Victory Theme", "Trophy Theme", "Ambient Grass",
    "Intro Cutscene", "Title Theme", "Darkmoon Caverns", "Jungle Falls", "Ancient Lake",
    "Frosty Village", "Secret Tune", "Fossil Canyon", "Hot Top Volcano", "Whale Bay",
    "Walrus Cove", "No Trophy For You", "Gold Balloons", "Collection Tune", "Main Lobby Area",
    "Party Pooper", "Everfrost Peak", "Wizpig Attacks", "Main Menu", "First Place",
    "Choose Your Racer", "Unknown 27", "Boss Challenge Victory", "Taj's Races",
    "Race Start Fanfare", "Greenwood Village", "Entranced", "Ambient Night", "Battle Theme",
    "Ambient Beach", "T.T.'s Theme", "Crescent Island", "Boss Challenge Failure", "Star City",
    "Boulder Canyon", "Ambient Unknown", "Spaceport Alpha", "Silver Coin 1", "Silver Coin 2",
    "Silver Coin 3", "Silver Coin 4", "Silver Coin 5", "Silver Coin 6", "Silver Coin 7",
    "Silver Coin 8", "Wizpig's Terror", "Boss Door Unlocked", "Wizpig's Final Challenge",
    "Key Collect", "Wizpig's Races", "Wizpig's Defeat", "Boss Challenges",
    "Wizpig Is Blasted Off", "Ending Party 1", "Ending Party 2", "Battle Victory",
    "Battle Lose", "Haunted Woods", "Ambient Haunted Woods", "Pirate Lagoon",
)


@dataclass(frozen=True)
class LevelField:
    key: str
    label: str
    group: str
    offset: int
    format: str
    minimum: int
    maximum: int
    description: str
    choices: Choices = ()

    @property
    def size(self) -> int:
        return struct.calcsize(">" + self.format)

    def read(self, data: bytes) -> SettingValue:
        values = struct.unpack_from(">" + self.format, data, self.offset)
        return values[0] if len(values) == 1 else values


VEHICLE_CHOICES: Choices = ((0, "Car"), (1, "Hovercraft"), (2, "Plane"))
VEHICLE_MASK_CHOICES: Choices = tuple((mask, " + ".join(name for bit, name in VEHICLE_CHOICES if mask & (1 << bit))) for mask in range(1, 8))
LEVEL_FIELDS: tuple[LevelField, ...] = (
    LevelField("laps", "Laps", "Race and vehicles", 0x4B, "b", 1, 3,
               "Race length: 1–3 laps. The game result/save paths store three lap times.", ((1, "1 lap"), (2, "2 laps"), (3, "3 laps"))),
    LevelField("vehicle", "Default vehicle", "Race and vehicles", 0x4D, "b", 0, 2,
               "Default player vehicle. Keep it included in Allowed vehicles. Menus/modes can override this default.", VEHICLE_CHOICES),
    LevelField("available_vehicles", "Allowed vehicles", "Race and vehicles", 0x4E, "B", 1, 7,
               "Bit mask: Car=1, Hovercraft=2, Plane=4. Keep the default vehicle included.", VEHICLE_MASK_CHOICES),
    LevelField("checkpoint_sets", "Checkpoint sets: Car, Hover, Plane", "Race and vehicles", 0x4F, "3b", 0, 127,
               "Three comma-separated checkpoint set IDs, not AI lane numbers. Changed IDs must exist among this level's main checkpoints."),
    LevelField("ai_adv1", "Adventure 1 AI presets", "AI difficulty", 0x20, "5b", 0, 127,
               "Five table IDs: base, silver coins, completed, Tracks mode, trophy race. These select existing AI presets, not a percentage."),
    LevelField("ai_adv2", "Adventure 2 AI presets", "AI difficulty", 0x25, "5b", 0, 127,
               "Same five modes for Adventure 2. IDs are checked against the actual AI behavior table."),
    LevelField("skybox_id", "Skybox header ID", "Environment", 0x38, "h", -1, 255,
               "Existing stock skybox header ID. skydome_spawn uses the direct-header flag, bypassing object translation. -1 means no skydome. Refreshes the optional environment preview."),
    LevelField("fog_near", "Fog near", "Environment", 0x3A, "h", 0, 1023,
               "N64 fog position, not world distance. The game swaps reversed near/far, caps far at 1023 and ensures a minimum gap of 5."),
    LevelField("fog_far", "Fog far", "Environment", 0x3C, "h", 0, 1023,
               "N64 fog position. All five fog values zero disables default fog. Fog trigger objects can override defaults in-game."),
    LevelField("fog_color", "Fog RGB", "Environment", 0x3E, "3h", 0, 255,
               "Red, green, blue (0–255 each), stored as three big-endian signed16 fields. Enable Saved fog in the environment toolbar to preview these defaults."),
    LevelField("camera_fov", "Camera field of view (degrees)", "Environment", 0x9C, "b", 1, 89,
               "The game's cam_set_fov accepts strictly 0 < FOV < 90. Optional FOV preview uses this value without changing camera speed."),
    LevelField("background_color", "Background RGB", "Environment", 0x9D, "3B", 0, 255,
               "Default background clear color, RGB 0–255. Used behind the saved sky in the optional environment preview."),
    LevelField("background_bottom", "Multiplayer gradient bottom RGB", "Environment", 0xBE, "3B", 0, 255,
               "Multiplayer background gradient bottom color."),
    LevelField("background_top", "Multiplayer gradient top RGB", "Environment", 0xC1, "3B", 0, 255,
               "Multiplayer background gradient top color."),
    LevelField("music", "Music sequence", "Music", 0x52, "B", 0, 255,
               "Existing sequence ID, checked against the ROM's ALSeqFile count. 0 skips level music start; event objects can override it. The editor does not play audio."),
    LevelField("instruments", "Music channel mask", "Music", 0x54, "H", 0, 65535,
               "Raw 16-channel mask passed to music_dynamic_set. Accepts decimal, 0x hex or 0b binary. Audio is not previewed."),
    LevelField("weather_density", "Weather density / enable", "Weather", 0x90, "h", 0, 32767,
               "0 disables initial weather. Positive values allocate snow particles (or enable rain). Editor caps new values at the largest stock header density to limit extra allocations."),
    LevelField("weather_type", "Weather type", "Weather", 0x92, "h", 0, 1,
               "0 Snow, 1 Rain. Used when density/enable is positive. Weather changes apply in-game; viewport weather preview is unavailable.", ((0, "Snow"), (1, "Rain"))),
    LevelField("weather_intensity", "Weather intensity", "Weather", 0x94, "B", 0, 255,
               "Raw byte; game multiplies it by 257 to obtain a weather intensity in 0–65535."),
    LevelField("weather_opacity", "Weather opacity", "Weather", 0x95, "B", 0, 255,
               "Raw byte; game multiplies it by 257 for weather opacity."),
    LevelField("weather_velocity", "Weather velocity X, Y, Z", "Weather", 0x96, "3h", -32768, 32767,
               "Three signed16 values, passed to weather_reset shifted left by 8. These are raw game units, not editor camera speed."),
)
FIELD_BY_KEY: dict[str, LevelField] = {field.key: field for field in LEVEL_FIELDS}


@dataclass(frozen=True)
class LevelReferences:
    ai_count: int
    music: Choices
    skyboxes: Choices
    max_weather_density: int
    checkpoint_sets: tuple[int, ...]


def base_references(rom: RomImage, catalog: LevelCatalog, database: ObjectDatabase) -> LevelReferences:
    # audio.c loads its sequence file from ASSET_AUDIO_TABLE entry4.
    audio_index = rom.section(AssetType.AUDIO_TABLE)
    sequence_offset = struct.unpack_from(">I", audio_index, 4 * 4)[0]
    audio = rom.section(AssetType.AUDIO)
    if sequence_offset + 4 > len(audio):
        raise AssetError("Music sequence header is outside the audio section")
    count = struct.unpack_from(">h", audio, sequence_offset + 2)[0]
    if not 1 <= count <= 256 or sequence_offset + 4 + count * 8 > len(audio):
        raise AssetError("Invalid music sequence count")
    music = tuple((i, SEQUENCE_NAMES[i] if i < len(SEQUENCE_NAMES) else f"Sequence {i}") for i in range(count))
    sky_ids = sorted({level.header.skybox_id for level in catalog.levels})
    skies = tuple((i, "None" if i == -1 else database.definitions[i].name) for i in sky_ids)
    density = max(struct.unpack_from(">h", level.header.raw_data, 0x90)[0] for level in catalog.levels)
    return LevelReferences(rom.count(AssetType.AI_BEHAVIOUR), music, skies, density, ())


def field_choices(field: LevelField, references: LevelReferences) -> Choices:
    if field.key == "music":
        return references.music
    if field.key == "skybox_id":
        return references.skyboxes
    return field.choices


def validate_header_edit(base: bytes, raw: bytes, references: LevelReferences) -> None:
    if len(raw) != 0xC8 or len(base) != 0xC8:
        raise AssetError("Editing requires the full 0xC8 serialized LevelHeader")
    LevelHeader.from_bytes(raw)
    allowed = {offset for field in LEVEL_FIELDS for offset in range(field.offset, field.offset + field.size)}
    if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(base, raw))):
        raise AssetError("Protected or unknown LevelHeader bytes must stay unchanged")
    for field in LEVEL_FIELDS:
        old, new = field.read(base), field.read(raw)
        before = old if isinstance(old, tuple) else (old,)
        after = new if isinstance(new, tuple) else (new,)
        for a, b in zip(before, after):
            if a == b:
                continue  # Preserve unsupported original values in unrelated fields.
            if not field.minimum <= b <= field.maximum:
                raise AssetError(f"{field.label}: expected {field.minimum}..{field.maximum}")
            choices = field_choices(field, references)
            if choices and b not in {value for value, _ in choices}:
                raise AssetError(f"{field.label}: choose an existing supported reference")
            if field.key.startswith("ai_") and not 0 <= b < references.ai_count:
                raise AssetError(f"AI preset ID must be in 0..{references.ai_count - 1}")
            if field.key == "checkpoint_sets" and b not in references.checkpoint_sets:
                raise AssetError("Checkpoint set does not exist among this level's main checkpoints")
            if field.key == "weather_density" and b > references.max_weather_density:
                raise AssetError(f"Weather density is capped at stock maximum {references.max_weather_density}")
    if base[0x4D:0x4F] != raw[0x4D:0x4F]:
        vehicle, mask = raw[0x4D:0x4F]
        if vehicle > 2 or not 1 <= mask <= 7 or not mask & (1 << vehicle):
            raise AssetError("Allowed vehicles must include the default vehicle")


def write_field(raw: bytes, key: str, value: SettingValue) -> bytes:
    field = FIELD_BY_KEY.get(key)
    if field is None:
        raise AssetError("This level field is protected or unknown")
    values = value if isinstance(value, tuple) else (value,)
    expected = len(struct.unpack_from(">" + field.format, raw, field.offset))
    if len(values) != expected or any(type(v) is not int for v in values):
        raise AssetError(f"{field.label} needs {expected} integer value(s)")
    result = bytearray(raw)
    try:
        struct.pack_into(">" + field.format, result, field.offset, *values)
    except struct.error as error:
        raise AssetError(str(error)) from error
    return bytes(result)
