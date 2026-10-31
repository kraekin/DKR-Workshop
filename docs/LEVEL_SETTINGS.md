# Saved level defaults

This milestone edits existing USA Rev 1 LevelHeaders, not object counts, map IDs,
track topology or compiled game rules. C size 0xC4; serialized records 0xC8. Unknown
bytes and the four-byte tail remain exact. Headers are uncompressed section 23,
indexed by section 22. Exports can combine header edits and relocated object maps.

Source evidence is local: include/structs.h:430, tools/fileTypes/levelHeader.hpp,
src/game.c:445–615/705–751, camera.c:204 and camera.h:24–25,
tracks.c:1322/4227, objects.c:1927–1950, weather.c:240–312,
audio.c:audio_init/music_sequence_start/music_dynamic_set and
include/sequence_ids.h; ALSeqFile is in include/PR/libaudio.h:281.

| Stored fields | Offset / BE format | Supported edit bounds |
|---|---|---|
|Adventure 1 / Adventure 2 AI presets|0x20 /0x25, each 5b|Five existing table IDs each: base, silver coins, completed, Tracks, trophy. Actual table contains 10 presets (0–9).|
|Skybox header ID|0x38,h|Stock-used skybox headers or -1. skydome_spawn uses OBJECT_SPAWN_UNK02, which bypasses object translation. Names must come directly from header IDs.|
|Fog near/far|0x3A/0x3C,h|0–1023, N64 fog positions, not world distance. Game swaps reversed endpoints, caps far and ensures a gap of 5.|
|Fog RGB|0x3E,3h|0–255 each. All five fog values zero resets fog. Trigger objects can override defaults.|
|Laps|0x4B,b|Conservative editor policy: 1–3. Stock headers use 1 or 3; result/save paths contain three lap times. Higher counts require their own audit.|
|Default vehicle|0x4D,b|0 Car, 1 Hovercraft, 2 Plane; must be included in allowed mask. Menus/modes can override it.|
|Allowed vehicles|0x4E,B|Bits1/2/4; new mask 1–7 must include the default. To switch a restricted vehicle, first allow both, then change default, then narrow the mask.|
|Checkpoint sets|0x4F,3b|Car/Hovercraft/Plane mapping. Changed values must exist among this level's main checkpoints. These are not AI lanes.|
|Music sequence|0x52,B|Existing ALSeqFile entries 0–65. Sequence 0 skips level_music_start; it is not a guaranteed global mute.|
|Music channel mask|0x54,H|0–65535; bit set enables that channel. 0xFFFF enables all 16 channels. Events may change music/mask.|
|Weather density/enable|0x90,h|0 disables startup weather. New values capped at 415, the stock maximum, as a conservative allocation policy. Positive snow density allocates particle arrays; rain only needs nonzero enable.|
|Weather type|0x92,h|0 Snow,1 Rain. Negative indexes are invalid for the preset array.|
|Weather intensity/opacity|0x94/0x95,B|0–255; game multiplies each by 257.|
|Weather XYZ velocity|0x96,3h|Signed16; passed to weather_reset shifted left 8, in raw game units.|
|Camera FOV|0x9C,b|1–89 degrees. cam_set_fov requires strictly 0<FOV<90; the struct comment alone was too permissive.|
|Background RGB|0x9D,3B|0–255 each.|
|Multiplayer gradient bottom/top|0xBE/0xC1,3B|0–255 each.|

Course height, special-sky mode/texture, waves, misc/pulse-light pointers, voice
limits, world/race/progression and geometry/map IDs remain protected. Preserve
unrecognized original values in unrelated fields instead of silently normalizing
them. Header overlays loaded from projects undergo the same validation as edits;
the project file cannot bypass protection by patching arbitrary header bytes.

UI: right inspector → Settings. Double-click values; named choices remain
editable numerically within supported bounds. Arrays use comma-separated values;
decimal/hex/binary work. Existing Level and Objects tabs retain their order.
Undo/redo is shared with objects across levels. Revert this level is one history
record and leaves object edits intact. Saving commits an active property editor.

Preview saved camera FOV changes the editor camera only, preserves movement speed
and position, and does not dirty the project. Stored FOV changes follow it while
enabled; disabling restores the prior editor FOV. Wheel zoom never edits the ROM.
Checkpoint mapping refreshes displayed routes. Fog, sky, music and weather are
saved for in-game testing; full environment/audio simulation remains later work.

Verification records are in STATUS.md. Automated tests cover all 65 unchanged
headers, each editable field's byte isolation, original tail/unknown preservation,
signed/array/reference bounds, malformed projects, mixed history, project reopen,
relocated ROM sections/checksums and unchanged original identity. Native checks
exercise real delegates/dropdown mouse selection, active-cell save, invalid edits,
FOV/camera invariants, revert and reopening a level 0 header overlay. In-game
confirmation of the new settings remains pending user review.
