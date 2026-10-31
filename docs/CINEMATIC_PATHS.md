# Cinematic and actor paths

v1.12.0 previews existing Animation tracks and edits their existing node fields.
It uses the selected ROM/project overlay. No nodes, object IDs or map entries
are added, removed or resized. Project version 6 and the protected ROM writer
are unchanged. This is an NTSC geometric preview, not a cutscene interpreter.

## Controls

Open **Tools → Cinematics** in the right inspector. Select the scene with the
existing Animation toolbar's **Scene** control. Ambient channel 20 remains
active alongside the selected scene; **Ambient only** excludes scene tracks.

- Select an actor/camera track. **Draw paths** shows green actor paths and pink
  camera paths, with selectable stored-node markers through terrain. Path
  visibility is independent of the Objects category filter.
- **Play**, **Rewind**, speed and scrub controls use the shared preview clock.
  The panel's time box allows exact seconds; **Range** changes the shared
  slider/loop from 10 to 300 seconds. **Move actors** switches between sampled
  track poses and initial poses, without editing records.
- The node list shows runtime ordinals, map/entry identities, first-arrival
  times discovered by sampling, and understood event requests. **Find node
  time** calculates first arrivals within Range and seeks the selected node.
  Input waits or scene switches can leave later nodes unreachable.
- Select a node and use the field selector, value and **Apply to node**. These
  are saved edits with ordinary undo/redo/project/export. For XYZ movement use
  the existing viewport handles, Placement tools or Objects position controls.
  Unknown fields/raw bytes remain accessible in Objects; they are not renamed
  from guesses. **Focus stored node** frames the actual editable node.
- For a camera track, **View through selected camera** applies its position,
  yaw, pitch and roll. Uncheck it or press Esc to restore the editor camera.
  Right mouse, Fit, changing view/level or focusing a node also exits camera
  preview. Movement speed, FOV and free-camera framing are preserved on exit.

The additional controls are in the inspector. The four compact toolbar rows
remain; Special art and the right-aligned environment controls share one row.

## Local source evidence

Authoritative files in `research/Diddy-Kong-Racing`:

- `include/level_object_entries.h`, `LevelObjectEntry_Animation` (0x32 / 50
  serialized bytes including the common 8-byte header; signed/unsigned types
  remain those of the existing object schema).
- `src/object_functions.c:obj_init_animation`: helper scale/rotations, actor ID
  sentinels, channel resolution and ambient high bit.
- `src/objects.c:func_8001E93C`: active helpers, actor/order sorting and runtime
  consecutive ordinals. Original stored order values are never rewritten by
  preview. Duplicate orders receive an action-flag ambiguity warning.
- `obj_init_animobject`, `func_8001F460`, `func_8002125C`, `func_800214E4`:
  initialization, two-pass distance correction, node events, pauses, speed
  inheritance, loops, clip state and terminal fallback.
- `catmull_rom_interpolation`, `cubic_spline_interpolation` and `lerp`: smooth
  position/scale/rotation, derivative and straight interpolation. Rotation
  components unwrap at half-turn boundaries. Scale remains Catmull–Rom even
  on straight position paths.
- `obj_loop_animcamera`, `camera.c:func_80067D3C`, and
  `src/hasm/math_util.c:mtxf_from_inverse_transform`: camera writes yaw
  `0x8000 - actorYaw`, pitch `-actorPitch`, roll `actorRoll`, followed by the
  camera view transform. The preview includes roll and source near/far 10/15000.

| Offset | Storage | Verified consumer / preview |
|---|---|---|
|08/09/0A|u8 Z/X/Y rotation|256 units per turn; interpolated yaw/pitch/roll|
|0B|u8 scale|min 1 / 64 × target header scale|
|0C|s16 objectIdToSpawn|Translation-table object ID of the first node's target|
|0E|s16 animationStartDelay|NTSC 60 Hz ticks; negative waits for external release|
|10/11|s8 actorIndex/order|Actor grouping, stable order and runtime ordinals|
|12/16/17/18|clip index / start / speed / mode|Mesh frames use sixteenths; modes 0 loop, 1 ping-pong, 2 once, 3 ping-pong once|
|14|s8 nodeSpeed|× 0.1 world units per tick; negative subsequent nodes inherit speed|
|19|u8 rotateType|First node: stored / spin / tangent / look-at actor|
|1A/1B/1C|s8 yaw/roll/pitch spin speeds|× 8 angle units per tick; runtime maps rollSpinSpeed to X and pitchSpinSpeed to Z|
|1D|s8 goToNode|Last-node loop ordinal; only count > 2 and 0..count-2 eligible|
|21|s8 channel|Selected scene plus ambient 20|
|24|s16 pauseFrameCount|-1 no pause; nonnegative pauses value + 1 unit ticks while traversing|
|26|s8 specialHide|Hide during pending start delay and at terminal fallback|
|2C|s8 nextAnim|Actor ID for rotateType 3 look-at, not a mesh clip selector|
|2D|s8 unk2D|0 smooth / nonzero straight position and stored-angle interpolation|

Message (27), music (1F), sound (1E), music fade (30), actor release (15), scene
switch (2A), particle mask (13), screen/fog fade (29) and actor fade flags (2F)
are identified by their consumers. Events are labeled as requests. Scene-switch
requests stop the local track; no automatic game-state transition is invented.

## Practical limits

- Playback uses one NTSC logic tick per 1/60 second, not the game's variable
  update rate, PAL adjustment, fixed-angle lookup quantization or collision
  response. Position/rotation are floating-point geometric previews.
- Live player camera/racer substitutions (`unk22`), override-position helpers,
  input waits, cross-actor release and scene chaining are not emulated. Warnings
  identify their presence. Negative start delays remain stopped.
- Actor look-at uses simultaneous preview poses; the game's actor update order
  can differ. Vehicle assemblies, racer approach/steering, character-select
  music synchronization and other target-specific behavior are not simulated.
- Short loop windows that run past the available controls are extended
  cyclically and labeled. Degenerate/overshooting paths stop with a diagnostic.
  Runtime append sentinels use the initial-load interpretation; duplicate
  orders retain map order and warn about action-dependent ties.
- Audio, text, particles, screen transitions and cinematic fog requests are
  event markers only. Actor fade flags preview visibility endpoints rather than
  intermediate alpha. Game lighting remains separate. Mesh clips use verified
  loop modes; billboard frame cycling retains the earlier sprite preview.
- Scrubbing, paths, range and camera mode are transient. Existing-node edits
  alone are saved. A first seek far into a long track computes its missing
  60 Hz samples; checkpoint caching makes backward/repeated seeks cheaper.

## Verification

Headless checks cover grouping/channels/ambient, duplicate orders and actor
sentinels, interpolation/derivative/endpoints/angle wrap, speed inheritance and
variation, start delays/pauses/loops, deterministic backward scrub, mesh clip
modes and changes, camera matrices, visibility endpoints, all 138 ROM maps and
byte-preserving edit/undo/project/in-memory export reload.

Native Qt/OpenGL checks cover all 65 levels and 263 scene choices, actor and
camera playback, selected-node editing and arrival seek, project reopen,
undo/redo, exact free-camera restoration, picking poses, resource reuse,
preview-only clean state and four toolbar rows at 1200/1440/1800 pixels wide.
See compact `STATUS.md` for final run results.

Cinematic preview does not run game scripts, physics or progression conditions.
Use an exported ROM to review those effects in-game.
