# Verified parameter labels

These names appear in the Objects inspector and, for animation nodes, in the
Cinematics field selector. They are display metadata in
`src/core/parameter_labels.py`; binary offsets, stored parameter keys and saved
project overlays are unchanged. Hover a field to see its original source name
and a description. Unknown fields remain editable through the normal parameter
and raw-byte controls; an unknown name is not evidence that a byte is unused.

Names were checked against the local `research/Diddy-Kong-Racing` checkout:
`include/level_object_entries.h` for layouts, `src/object_functions.c` for object
initializers and updates, `src/objects.c` for animated-object, checkpoint, fish
rendering and music-zone consumers, and `src/weather.c` for weather inputs.
Animation meanings follow actual consumers, including fields with misleading
source names: `soundEffect` selects transition color and `nextAnim` selects a
look-at actor. These labels do not add runtime simulation to the viewport.

Animation bytes `0x23` and `0x31` remain unknown. Checkpoint `0x18`/`0x1B` and
weapon balloon `0x08` have no identified reader in the inspected Rev 1 behavior;
their original purpose remains unknown. Other unresolved fields keep their
offset rather than receiving an inferred name.

## Fish

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unk8` | Swim radius | Horizontal figure-eight path radius in game units. |
| `unkA` | Depth variation | Maximum random vertical excursion around the stored home height. |
| `unkB` | Texture variant | Selects one of this fish definition's textures, with fallback to variant 0. |
| `unkC` | Scale | Raw value × 0.01. |
| `unkD` | Height scale | Additional vertical artwork scale: raw value × 0.01. |
| `unkE` | Swim speed | Path phase advance per tick: raw value × 16 binary-angle units. |
| `unkF` | Swim path yaw | Orientation of the horizontal path: 256 units per revolution. |

## Checkpoints

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `scale` | Path scale | Raw scale byte. The game uses max(value, 5) / 32 for lane offsets. Also scales alternate-entry proximity; the marker sphere is an editor aid. |
| `index` | Checkpoint index | Order within this checkpoint set. Alternate checkpoints pair with the main checkpoint of the same index. |
| `angleY` | Yaw | Raw yaw byte: 5.625 degrees per unit, wrapping every 64. Sets the crossing plane and sideways offset direction. |
| `isAltCheckpoint` | Alternate checkpoint | Nonzero marks an alternate paired with the same main index and checkpoint set. |
| `unk18` | Unused byte (0x18) | No checkpoint reader identified in Revision 1; all original checkpoints store -1. The original purpose is unknown. |
| `unk19` | HUD course cue | On crossing, requests a course cue for 120 timer units. Course directions must be enabled; displayed in single-player before race finish. Zero does not cancel an active prior cue. |
| `vehicleType` | Checkpoint set | Set ID selected through the level header's Car/Hovercraft/Plane mapping. Four AI lane numbers are independent of the vehicle and set IDs. |
| `unk1B` | Unused byte (0x1B) | No checkpoint reader identified in Revision 1; all original checkpoints store 0. The original purpose is unknown. |
| `unkB` | AI lane 0 lateral | Signed sideways offset for AI lane 0. World offset = value × max(scale, 5) / 32, rotated by checkpoint yaw. AI racers can switch lanes during a race. |
| `unkF` | AI lane 0 height | Signed vertical offset for AI lane 0. Adds value × max(scale, 5) / 32 to the path height. Vehicle physics still apply. |
| `unk13` | AI lane 0 behavior | Behavior selector for lane 0, not bit flags. 1: Bluey turn / Wizpig jump or flying animation. 2: AI alternate route on passing. 3: unidentified. 4: physical AI slowdown. 5: keeps detailed AI simulation active and selects alternate route in water. 6: sets lap to race laps + 1. Effects depend on racer/context; existing alternate nodes define alternate routes. |
| `unkC` | AI lane 1 lateral | Signed sideways offset for AI lane 1. World offset = value × max(scale, 5) / 32, rotated by checkpoint yaw. AI racers can switch lanes during a race. |
| `unk10` | AI lane 1 height | Signed vertical offset for AI lane 1. Adds value × max(scale, 5) / 32 to the path height. Vehicle physics still apply. |
| `unk14` | AI lane 1 behavior | Behavior selector for lane 1, not bit flags. 1: Bluey turn / Wizpig jump or flying animation. 2: AI alternate route on passing. 3: unidentified. 4: physical AI slowdown. 5: keeps detailed AI simulation active and selects alternate route in water. 6: sets lap to race laps + 1. Effects depend on racer/context; existing alternate nodes define alternate routes. |
| `unkD` | AI lane 2 lateral | Signed sideways offset for AI lane 2. World offset = value × max(scale, 5) / 32, rotated by checkpoint yaw. AI racers can switch lanes during a race. |
| `unk11` | AI lane 2 height | Signed vertical offset for AI lane 2. Adds value × max(scale, 5) / 32 to the path height. Vehicle physics still apply. |
| `unk15` | AI lane 2 behavior | Behavior selector for lane 2, not bit flags. 1: Bluey turn / Wizpig jump or flying animation. 2: AI alternate route on passing. 3: unidentified. 4: physical AI slowdown. 5: keeps detailed AI simulation active and selects alternate route in water. 6: sets lap to race laps + 1. Effects depend on racer/context; existing alternate nodes define alternate routes. |
| `unkE` | AI lane 3 lateral | Signed sideways offset for AI lane 3. World offset = value × max(scale, 5) / 32, rotated by checkpoint yaw. AI racers can switch lanes during a race. |
| `unk12` | AI lane 3 height | Signed vertical offset for AI lane 3. Adds value × max(scale, 5) / 32 to the path height. Vehicle physics still apply. |
| `unk16` | AI lane 3 behavior | Behavior selector for lane 3, not bit flags. 1: Bluey turn / Wizpig jump or flying animation. 2: AI alternate route on passing. 3: unidentified. 4: physical AI slowdown. 5: keeps detailed AI simulation active and selects alternate route in water. 6: sets lap to race laps + 1. Effects depend on racer/context; existing alternate nodes define alternate routes. |

## Doors

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unk10` | Blocked vehicle mask | Vehicles prevented from opening the door: bit 0=Car, bit 1=Hovercraft, bit 2=Plane. |

## Weapon balloons

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unk8` | Unused byte (0x08) | The Revision 1 weapon-balloon initializer does not read this field; its original purpose is unknown. |

## Texture scrolling

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unkA` | U scroll speed | Signed horizontal scroll rate; 128 units correspond to one texel per NTSC tick. |
| `unkB` | V scroll speed | Signed vertical scroll rate; 128 units correspond to one texel per NTSC tick. |

## Weather triggers

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unkA` | Weather velocity X | Horizontal weather velocity, passed to weather_set as raw value × 256. |
| `unkC` | Weather velocity Y | Vertical weather velocity, passed to weather_set as raw value × 256. |
| `unkE` | Weather velocity Z | Horizontal weather velocity, passed to weather_set as raw value × 256. |
| `unk10` | Weather intensity | Intensity passed to weather_set as raw value × 257. |
| `unk11` | Weather opacity | Opacity passed to weather_set as raw value × 257. |
| `unk12` | Weather transition ticks | Duration passed to weather_set. Positive values enable the transition. |

## Bridges / whale ramps

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unkA` | Bridge timer ID | Connects the bridge to its ramp switch; also selects the bell position for a drawbridge. |
| `unkB` | Bridge activation mode | Selects proximity, timer, vehicle or drawbridge behavior. |
| `unkD` | Bridge hold ticks | Timer activation holds the bridge for raw value × 2 ticks, refreshed while the switch timer is active. |

## Ramp switches

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unk8` | Bridge timer ID | Timer started by this switch when a racer is within 45 game units. |

## Animation path nodes

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `z_rotation` | Roll | Unsigned angle: 256 units per revolution. |
| `x_rotation` | Pitch | Unsigned angle: 256 units per revolution. |
| `y_rotation` | Yaw | Unsigned angle: 256 units per revolution. |
| `scale` | Scale | max(raw value, 1) / 64, multiplied by the spawned object definition scale. |
| `objectIdToSpawn` | Spawn object ID | Object translation-table ID for this actor; negative values do not spawn an object. |
| `animationStartDelay` | Start delay | NTSC timer ticks. Negative values wait for input or another actor to release this actor. |
| `actorIndex` | Actor ID | Nodes with the same actor ID form a path. -2 reuses the preceding ID; -1 resolves to 0. Ambient actors use a separate signed ID range. |
| `order` | Node order | Stored path order. The game sorts these nodes before playback. |
| `objAnimIndex` | Model animation clip | Clip index within the spawned model. On subsequent nodes, negative values keep the current clip; use a valid clip on the first node. |
| `unk13` | Particle emitter mask | Nonnegative values select enabled particle emitters by bit mask. Negative values retain the previous mask. |
| `nodeSpeed` | Travel speed | Raw value × 0.1 game units per NTSC tick. Negative values retain the previous speed. |
| `unk15` | Release actor ID | Nonnegative values release another actor that is waiting on a negative start delay. |
| `unk16` | Initial clip frame | Initial model-animation frame in sixteenths. Also used when changing clips. |
| `objAnimSpeed` | Clip speed | Model-animation progress per NTSC tick, measured in sixteenths of a frame. |
| `objAnimLoopType` | Clip playback | Loop behavior of the model animation. |
| `rotateType` | Rotation mode | Controls stored rotations, continuous spin, tangent following or look-at behavior. |
| `yawSpinSpeed` | Yaw spin speed | Signed angular increment used by spin rotation mode. |
| `rollSpinSpeed` | Roll spin speed | Signed angular increment used by spin rotation mode. |
| `pitchSpinSpeed` | Pitch spin speed | Signed angular increment used by spin rotation mode. |
| `goToNode` | Loop target node | Last-node loop target ordinal. -1 ends the path; eligible paths can loop to an earlier node. |
| `unk1E` | Sound ID | Sound request: 0 makes no request; 255 stops the previous actor sound. |
| `unk1F` | Music ID | Positive values request a music sequence. Nonpositive values make no music request. |
| `unk20` | Input release buttons | Buttons that release a negative start delay: bit 0=A, bit 1=B, bit 2=Start. |
| `channel` | Scene channel | Scene ID; 20 is ambient playback and -1 resolves to the active scene. |
| `unk22` | Live actor / camera mode | Selects live transform behavior. 0 uses stored nodes; 1 uses camera control points; 10–17 copy racer transforms; 18 copies the active camera transform. Other values also affect actor initialization. |
| `pauseFrameCount` | Pause ticks | Nonnegative values pause at the node; -1 disables the pause. |
| `specialHide` | Hide on delay / finish | Nonzero hides the actor while delayed or after the path finishes. |
| `messageId` | Message ID | Requests a game-text message. 255 disables the request. |
| `unk28` | Advance scene counter | A nonnegative value increments the active scene counter when this node is reached. Negative values leave it unchanged. |
| `unk29` | Screen transition / fog | Low seven bits select a transition or fog preset; 127 disables the request. The high bit changes transition direction/behavior. |
| `unk2A` | Switch scene ID | Nonnegative values switch the active game scene when this node is reached. |
| `fadeAlpha` | Transition duration | Duration multiplier for screen transitions and fog changes; the game scales it by its six-tick interval. |
| `nextAnim` | Look-at actor ID | Actor target for look-at rotation mode. This is not a model-animation clip index. |
| `unk2D` | Path interpolation | Position and rotation interpolation; scale retains smooth interpolation. |
| `soundEffect` | Transition color index | Color-table index used by screen transitions; this field does not select a sound effect. |
| `fadeOptions` | Actor opacity flags | Bit 0 fades out instead of in; bit 1 resets opacity before fading. |
| `unk30` | Music fade | Signed music-fade request, scaled by 256. Zero leaves the current fade unchanged. |

## Triggers

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unkB` | Message ID | Text requested on crossing. 255 disables the message. |
| `unkC` | Release ambient actor ID | Values 0–127 release a waiting ambient actor. The game adds 128 and wraps to eight bits; 255 disables the request. |
| `unkD` | Excluded racer mask | Bit 0 excludes computer racers; bit 1 excludes human racers from activating this trigger. |

## Butterflies

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unk8` | Roaming / trigger radius | Radius used to search for nearby racers or butterfly targets; some flight states use twice this radius. |
| `unkA` | Texture variant | Selects the butterfly texture; variant 2 also changes flight behavior. |
| `unkB` | Scale | Raw value × 0.01. |

## Music fade planes

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unkA` | Channel fade actions | 16 stored channel bytes. Bits 0–1 apply in one crossing direction; bits 2–3 in the other. Actions: 0 off, 1 on, 2 fade out, 3 fade in. |
| `unk1A` | Fade duration seconds | Transition duration multiplied by the video refresh rate. |
| `unk1B` | Music ID | Fade zone only applies while this music sequence is playing. |

## T.T. doors

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unk9` | Open yaw | Open-door yaw: 64 units per revolution, using the low six bits. |

## Music fade points

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unk8` | Inner fade radius | Distance at which the inner channel mix is reached. |
| `unkA` | Outer fade radius | Distance at which the outer channel mix is reached; the game corrects values below the inner radius. |
| `unkC` | Channel fade actions | Stored channel array: action 1 fades out with distance, action 2 fades in with distance. The initializer copies only the first 15 bytes. |
| `unk1C` | Music ID | Distance fade only applies while this music sequence is playing. |

## Music channel triggers

| Stored field | Display label | Meaning / units |
| --- | --- | --- |
| `unk8` | Music channel mask | Channel mask passed to music_dynamic_set while this music sequence is playing. |
| `unkA` | Activation radius | Raw value × 4 game units. |
| `unkB` | Music ID | Channel change only applies while this music sequence is playing. |
