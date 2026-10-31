# Environment preview

The Environment toolbar previews saved sky/background and fog defaults, track
flipbooks, placed texture scroll controllers and approximate waves. The existing
Play/Pause, Rewind, time slider and rate drive all motion deterministically.
Controls never enter project history or change saved asset bytes. Settings,
object properties and image replacements still use their existing writers.
The environment controls share the Special art row and align to the right;
toolbar padding is compact. The information icon retains preview-limit notes.
Native layout checks pass at1200/1440/1800px with four rows and a taller viewport.

Sky/background, texture motion and water start enabled; Saved fog starts disabled
so distant geometry remains easy to edit. Fog is perspective-only. Multiplayer
gradient substitutes the saved gradient for the sky. Water is temporarily bypassed
while material editing exposes the original stored faces/UVs.

## Local source and units

All references are in `research/Diddy-Kong-Racing`.

- `tracks.c:skydome_spawn/skydome_render` selects a direct ObjectHeader, first
  object model and header scale. Mode0 centers it on the current camera. The
  renderer uses the ROM mesh/colors/textures without letting it write scene depth.
  `game.c:591` supplies background RGB. `tracks.c:trackbg_render_gradient` supplies
  the optional multiplayer gradient colors.
- The one stock special sky (level55, mode−1) uses
  `tracks.c:trackbg_render_flashy`: the source nine-vertex plane at cameraY+192,
  source eight triangles, yaw/camera-dependent UVs and header A0/A1 scale plus
  signed A2/A3 scrolling. Its texture ID comes from header A4; game.c resets the
  runtime A8/AA accumulators to zero. The color/keyframe scripts are omitted.
- `game.c:557`, `tracks.c:set_fog` and `include/PR/gbi.h:gSPFogPosition` define
  the fog defaults and projection-space units. Reverse near/far are swapped,
  far is capped at1023 and the gap is at least5. All five zero fields reset fog
  beyond visible depth. The shader computes the same depth position using the
  game's `camera.h` near10/far15000, independent of the editor's safety clip
  planes, and interpolates a vertex fog factor. Gizmos/sky are not fogged.
- `tracks.c:track_tex_anim` and `textures_sprites.c:tex_animate_texture` define
  discrete60Hz flipbooks: flag10000, forward/reverse and ping-pong modes, static
  batch offset and optional bit31 fractional retention. Six low counter bits are
  discarded by the track unless bit31 retains them in miscData. Random-trigger
  batches remain at their stored state; already-active one-shots run to rest.
  Cycles are cached and scrubbed by absolute time; source flags/bytes stay intact.
- `object_functions.c:5499–5618` and `level_object_entries.h:TexScroll` define
  12-byte controllers: s16 texture slot@08, signed s8 U/V rates@0A/0B. Each keeps
  two fractional bits independently; UV changes are `floor(rate*ticks/4)` in
  s10.5 units. Wrap uses eight texture widths/heights based on uv0; all three
  corners move together. Triangle flag80 excludes scrolling. Slots clamp to the
  actual level texture array. Multiple controllers retain independent fractions.
- `waves.c:waves_init_header/waves_init/waves_update/waves_render`,
  `structs.h:LevelHeader` and `LevelModelSegment` define wave previews. Relevant
  header bytes are56–71: subdivisions/tile count, two sine steps/phases/heights,
  signed16 seed size@60 (rounded even), power@62, shade scale@66, texture@68,
  UV scale@6A/6B and signed scroll@6C/6D, translucency@70 and double density@71.
  Heights/power/shade scale divide by256. Phases shift by8; sine steps divide
  one16-bit turn by the seed size. The WAVF seeded phase grid follows
  `hasm/math_util.c:rand_range`; each60Hz tick advances table indices by one.
  Segment hasWaves is byte2B of each44-byte serialized segment.

Water tessellates eligible stored water faces inside those segments, preserving
their footprints and holes. It samples the seeded sine field continuously,
applies source UV scaling/scroll and combines the source base and detail textures
using the verified two-cycle blend in `f3ddkr.h`. The translucent shade/alpha
ramps follow `waves.c:func_800B92F4` with a fixed mid-intensity lighting sample.
Lava uses the source opaque path's base texture. Both source texture inputs honor
PNG overlays. GPU frames and buffers are retained during playback.

## Approximation boundaries

This is a preview of defaults, not a game-state simulation. Fog/sky triggers,
weather/rain effects, particles, game lights, flashes/color scripts and live
progression conditions are not evaluated. Water omits camera/racer-dependent
tile allocation, edge damping, noise lighting/fades, swell generators and object
buoyancy. Tessellation is capped at12 subdivisions per stored triangle; this
preserves shorelines rather than reproducing the game's visibility-managed grid.
Wave environment tint records are not simulated. Float trigonometry/clipping
does not reproduce all N64 fixed-point rounding. Structured extracted headers
without retained wave bytes show static water rather than invented defaults.

## Verification

Headless checks cover fog units/clamps, frame modes/fraction retention, one-shots,
long scrub, wave offsets/signs, seeded grid/time/continuity, per-controller scroll
fractions, special-sky geometry and unchanged sessions. All65 stock levels are
checked; native RTX checks cover sky/fog/gradient/waves, frame/UV GPU updates,
saved-default refresh without camera movement, repeated scrub and level changes,
GL resource stability and clean project history. About63FPS with no GL errors.
No review ROMs or emulator runs are generated; gameplay testing is performed by
the user.
