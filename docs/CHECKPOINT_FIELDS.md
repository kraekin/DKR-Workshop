# Revision 1 checkpoint field guide

Findings from the authoritative local DKR decomp and the original USA Rev 1
ROM, investigated 2026-10-19. These are source/ROM findings; new gameplay
experiments have not been run in an emulator. Original source names are retained
below as parser keys. The v1.3.2 inspector displays friendly labels; hovering a
label reveals its original field name and explanation. Binary schemas and saved
projects retain their existing keys and offsets.

## Entry layout and field meanings

`LevelObjectEntry_Checkpoint` is **28 bytes / 0x1C**. All listed fields are one
byte; `s8` means signed -128..127, `u8` means unsigned 0..255. The preceding
8-byte common header holds object ID, entry length and BE signed16 XYZ.

| Offset | Source/key name | Type | Meaning supported by code |
|---|---|---|---|
| 0x08 | scale | u8 | Path scale, clamped to at least 5, then divided by64 for the checkpoint object; runtime node scale is twice that. Scales AI offsets and the alternate-entry proximity radius. |
| 0x09 | index | u8 | Order within the selected checkpoint set. An alternate pairs with the main checkpoint of the same index. |
| 0x0A | angleY | u8 | Checkpoint orientation. Converted with `angleY << 10` into a 16-bit angle: 5.625 degrees per unit, wrapping every 64. Sets crossing-plane direction and lateral-offset orientation. |
| 0x0B | unkB | s8 | AI lane 0 lateral offset. |
| 0x0C | unkC | s8 | AI lane 1 lateral offset. |
| 0x0D | unkD | s8 | AI lane 2 lateral offset. |
| 0x0E | unkE | s8 | AI lane 3 lateral offset. |
| 0x0F | unkF | s8 | AI lane 0 vertical offset. |
| 0x10 | unk10 | s8 | AI lane 1 vertical offset. |
| 0x11 | unk11 | s8 | AI lane 2 vertical offset. |
| 0x12 | unk12 | s8 | AI lane 3 vertical offset. |
| 0x13 | unk13 | s8 | Lane0 special behavior selector; see codes below. |
| 0x14 | unk14 | s8 | Lane1 special behavior selector. |
| 0x15 | unk15 | s8 | Lane2 special behavior selector. |
| 0x16 | unk16 | s8 | Lane3 special behavior selector. |
| 0x17 | isAltCheckpoint | u8 | Nonzero marks an alternate checkpoint, paired by index with a main one in the same set. |
| 0x18 | unk18 | s8 | Apparently unused in this revision: no checkpoint-field reader found; all 1,256 original checkpoints contain -1 here. Original intended meaning remains unknown. |
| 0x19 | unk19 | u8 | HUD course-direction cue, triggered when crossing the checkpoint plane. See cue values below. |
| 0x1A | vehicleType | s8 | Checkpoint set ID, selected through the level header's per-vehicle mapping. It is not intrinsically a Car/Hovercraft/Plane enum. |
| 0x1B | unk1B | u8 | Apparently unused trailing byte: no checkpoint-field reader found; all 1,256 original checkpoints contain0. Do not assign a stronger meaning without further evidence. |

Sources: [serialized definition](../research/Diddy-Kong-Racing/include/level_object_entries.h#L131),
[initializer](../research/Diddy-Kong-Racing/src/object_functions.c#L3194),
[runtime construction and lane copies](../research/Diddy-Kong-Racing/src/objects.c#L5530),
[AI offsets](../research/Diddy-Kong-Racing/src/racer.c#L1417),
[AI spline offsets](../research/Diddy-Kong-Racing/src/racer.c#L9060).

## Four lanes and their coordinate units

Each lane uses three separate bytes, not three adjacent bytes:

| Lane | Lateral | Vertical | Behavior |
|---|---|---|---|
| 0 | unkB | unkF | unk13 |
| 1 | unkC | unk10 | unk14 |
| 2 | unkD | unk11 | unk15 |
| 3 | unkE | unk12 | unk16 |

These four lanes are independent of vehicle choice. The AI selects lane index
`racer->unk1CA` and can change it with race position and nearby-racer decisions.
Boss/Taj logic can select lane 0; a finished human racer can be driven on lane 1.
Changing only lane 0 does not necessarily affect every computer racer.
Sources: [lane selection](../research/Diddy-Kong-Racing/src/racer.c#L313),
[passing and special-race selection](../research/Diddy-Kong-Racing/src/racer.c#L435),
[post-finish AI](../research/Diddy-Kong-Racing/src/racer.c#L4277).

Let `S=max(scale,5)/32`, and let theta be the checkpoint's effective yaw. For
that lane's lateral L and vertical V, the path control point is:

```text
X = checkpoint.X + S * cos(theta) * L
Y = checkpoint.Y + S * V
Z = checkpoint.Z - S * sin(theta) * L
```

The game interpolates a spline through these points. Offsets influence the
surrounding curve as well as the checkpoint itself. Ground collision and vehicle
physics still apply; raising an AI target is not a command to levitate a car.
The main checkpoint crossing test uses an oriented plane; the editor's generic
marker sphere is not a drawing of a physical checkpoint hitbox. `scale` also
sets the alternate-entry proximity radius to `2*max(scale,5)` game units.
See [crossing/proximity tests](../research/Diddy-Kong-Racing/src/objects.c#L5715).

From v1.25.2 the marker arrow shows intended travel along the checkpoint's
local **-Z**, matching the start-grid arrows. Earlier versions drew local +Z,
the crossing-plane normal, so arrows appeared backwards. This is only a display
correction; stored angles, crossing planes and AI lane calculations are unchanged.

For the checkpoint in the user's screenshot, **map 5 / entry 48, index 0**:

- XYZ=(-1540,51,-7607), scale 95, angleY 0.
- Lateral values are [-53,-15,28,64]; all vertical offsets are 0.
- S=2.96875, so lane X offsets are [-157.34375,-44.53125,83.125,190].
- Lane X positions are [-1697.34375,-1584.53125,-1456.875,-1350]; Y remains 51.
- Behavior codes are all 0; unk19=1 requests a left-turn course cue.
- Ancient Lake's header maps Car/Hovercraft/Plane to sets(0,0,1). This
  checkpoint belongs to set 0, used by Car and Hovercraft. Planes use set 1.

Source for selecting the set: [game.c](../research/Diddy-Kong-Racing/src/game.c#L492).

## Lane behavior codes: unk13 through unk16

The game compares these bytes for equality with individual values. They are
**selectors, not combinable bit flags**. Evaluation uses the active lane at the
current upcoming checkpoint; some actions additionally require crossing it.

| Code | Confirmed use |
|---|---|
| 0 | No additional behavior selected by the inspected branches. |
| 1 | Boss animation cue. Bluey uses it for the special turn animation; Wizpig uses it to transition from running into a jump/flying sequence. |
| 2 | Sets the computer racer's alternate-route state when the checkpoint is passed. Existing paired alternate checkpoints define where that route goes. |
| 3 | No explicit consumer found, and no original checkpoint lane contains this value. Original purpose unknown. |
| 4 | In the physical AI update, multiplies forward velocity by 0.9 while velocity<-4. This is an AI slowdown cue. |
| 5 | Keeps the physical AI-update timer at 30; when the racer has a nonzero waterTimer, sets alternate-route state. The main racer update also applies the water/alternate check to computer racers. |
| 6 | Sets the racer's lap counter to configured laps+1. Present in both main and physical AI updates; it is not an arbitrary weapon/speed setting. This does not directly assign raceFinished in that branch. |

Context matters: ordinary human steering does not follow an AI lane, and some
behavior branches apply only to computer racers or particular bosses. AI code
can use a simplified spline update when far from the player. Code 5's timer
keeps the detailed physical update active while its branch is evaluated.

Sources: [main racer update](../research/Diddy-Kong-Racing/src/racer.c#L4463),
[physical AI update](../research/Diddy-Kong-Racing/src/racer.c#L8838),
[physical/simplified AI selection](../research/Diddy-Kong-Racing/src/racer.c#L8722),
[Bluey animation](../research/Diddy-Kong-Racing/src/vehicle_bluey.c#L120),
[Wizpig animation](../research/Diddy-Kong-Racing/src/vehicle_wizpig.c#L134).

Stock evidence supports these specialized roles: code 1 occurs in WizPig 1;
code 2 in Fossil Canyon, Snowball Valley and Crescent Island; code 5 in Boulder
Canyon; codes 4/6 in TrickyTops tracks, and code 6 also in the Walrus boss tracks.
Across all 5,024 lane-selector bytes, counts are 0:4958,1:19,2:3,4:24,5:4,6:16.

## HUD cue: unk19

| Value | Cue |
|---|---|
| 0 | No new cue; does not explicitly cancel a still-active prior cue. |
| 1 | Left turn (45-degree artwork). |
| 2 | Sharp left (90-degree artwork). |
| 3 | Left U-turn. |
| 4 | Right turn (45-degree artwork). |
| 5 | Sharp right (90-degree artwork). |
| 6 | Right U-turn. |
| 7 | Up. |
| 8 | Down. |
| 9 | Exclamation mark. |

On crossing, nonzero unk19 is copied to racer.indicator_type and its timer is
set to 120. Rendering requires course directions enabled, one-player HUD, race
not finished and no overriding HUD warning timer. In an active normal
single-player race, C-down toggles course directions. Mirrored-track mode flips
left/right artwork. Other nonzero values fall through to exclamation artwork;
the table above is the defined enum.
Sources: [cue trigger](../research/Diddy-Kong-Racing/src/objects.c#L5795),
[enum](../research/Diddy-Kong-Racing/src/game_ui.h#L69),
[HUD rendering](../research/Diddy-Kong-Racing/src/game_ui.c#L979),
[C-down toggle](../research/Diddy-Kong-Racing/src/game_ui.c#L719).

## Controlled experiments

In v1.3.2, unkB is displayed as **AI lane 0 lateral**, unkF as **AI lane 0
height**, unk13 as **AI lane 0 behavior**, and unk19 as **HUD course cue**.
The other lanes follow the same pattern. Behavior, cue and alternate-status
cells offer named choices while retaining raw integer entry for experiments.
The two apparently unused bytes and unidentified behavior code3 remain marked
as uncertain. Selection, raw edits and project/export serialization still use
the original keys and byte offsets.

1. In the current editor, turn on Racelines, select Car, then All AI lanes.
   For map 5 / entry 48, change unkB from -53 to -43. Only lane 0's control point
   should shift +29.6875 along world X; its surrounding curve will change too.
   Undo afterward. A separate in-memory edit verified this displacement,
   unchanged other lanes, only byte 0x0B changed, and complete undo restoration.
2. For a human-visible in-game test, change unk19 from 1 to 4. Export a new ROM,
   boot it and reload the level, keep course directions enabled, and cross that
   checkpoint normally. The cue should change from left to right. Restoring an
   old savestate can retain the previously loaded map or runtime checkpoint array.
3. For AI behavior tests, use the active checkpoint set and an appropriate
   race context. Record the lane actually used, or apply the same test code to
   all four behavior bytes if the experiment is meant to affect all AI lanes.
   Compare position/route/animation/lap state rather than relying only on speed.

No emulator experiment above was executed during this investigation. The source
and ROM scan establish the mappings; exact visible timing/physics remains a
runtime validation task. No values in the user's running editor were changed.

For debugger follow-up, local us.v80 symbols give obj_init_checkpoint=0x8003ACFC,
checkpoint_update_all=0x80017ECC, checkpoint_is_passed=0x80018618 and
hud_course_arrows=0x800A13F4. Inspect the runtime copy, not only the spawn byte:
CheckpointNode has lane lateral bytes at 0x2E..31, vertical at 0x32..35,
behavior at 0x36..39, and course cue at 0x3B. The racer lane selector is at 0x1CA.
Runtime pointers must be located for the current load, not treated as ROM offsets.

## ROM scan summary

All 138 object-map slots were read without modification: 1,256 checkpoint entries,
1,218 main and 38 alternate. Set counts are 0:1029,1:207,2:20. Lateral values range
-117..122; vertical values -92..72. All unk18=-1, all unk1B=0. Cue values
are 0..9, with0:891,1:110,2:27,3:6,4:120,5:32,6:3,7:4,8:6,9:57.
These distributions support the source trace but do not alone prove a meaning.

User gameplay confirmation (2026-10-19): changing the renamed HUD course cue
from Left to Right made the game display the right-turn indication at that turn.
