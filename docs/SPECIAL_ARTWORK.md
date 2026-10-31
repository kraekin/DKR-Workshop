# Special physical artwork

All textures are read from the selected ROM or extracted
assets, including project image replacements. The new meshes are preview data;
they never enter the project overlay or ROM writer. Preview controls do not alter saved assets.

## Controls

**Special art** independently shows ground zippers, fish, butterflies and portrait
samples. Inspector filters and **Objects** only control helper gizmos. Artwork
remains pickable with helpers hidden and follows existing position/property edits,
mouse moves and undo. Double-click a list row to frame its displayed geometry.
**View → Special artwork** restores the toolbar if hidden.

The existing **Animation preview** Play/Pause, Rewind, time slider and rate apply
to the animals too. Previews start paused. Fish use a deterministic home loop at
the stored depth; butterflies preview idle wings at their stored positions.
**Portrait sample** chooses one character for all portrait slots, or Off. Diddy
is the default sample. The game instead chooses each slot's live racer character.
Neither this choice, visibility nor playback changes saved bytes. The inspector's
**Artwork preview** row explains each affected behavior's limitations.

## Verified local source

All paths below are relative to `research/Diddy-Kong-Racing`; no online sources
were used. Existing LUT, compression and struct parsers remain unchanged.

| Graphic | Source and stored data | Preview |
|---|---|---|
|Ground zipper, behavior82|`object_functions.c:953–1005`; `objects.c:2379–2398`; `tracks.c:3542–3958`, `func_800304C8`; `structs.h:ObjectHeader`; `textures_sprites.h` render flags|Project header shadow texture onto clipped eligible track facets.|
|Fish, behavior3|`object_functions.c:49–65,1418–1620`; `objects.c:3281–3286`; `level_object_entries.h:446–455`|Six vertices, eight opposing-winding faces, source UVs, scaled body and bending tail, deterministic figure-eight home loop.|
|Butterfly, behavior61|`object_functions.c:80–93,5811–6180`; `objects.c:3276–3280`; `level_object_entries.h:439–444`|Six vertices, eight opposing-winding faces, source UVs and idle wing equations. Variant2 uses the source's fixed idle frame120.|
|Character portrait, behavior47|`object_functions.c:42–47,1082–1134`; `objects.c:3268–3274`; `level_object_entries.h:356–362`; `enums.h:Character`|Four-vertex 512×512 local quad, two double-sided faces, selected texture, source scale and yaw.|
|Boost, behavior89|`object_functions.c:6354–6358`; `objects.c:racerfx_alloc`, `render_3d_misc`, `func_800135B8`|Retains a gizmo, explicitly labeled runtime-only.|

`objects.c:2076` loads misc model IDs through `load_texture`. In
`textures_sprites.c:455–481`, an ordinary ID selects **2D** textures; bit0x8000
selects **3D**. Thus the stock ground zipper uses 2D texture16, not 3D texture16.
The misc headers reference 2D fish76, butterflies73–75 and portraits
122,123,124,126,125,127,128,129,130,131. Portrait enum order is Krunch, Bumper,
Tiptup, Conker, Timber, Banjo, Drumstick, Pipsy, T.T., Diddy. IDs are read from
headers, not hardcoded into the renderer. Extracted ObjectHeader JSON resolves
misc `models` to 2D texture IDs, matching `extractObjectHeader.cpp:143–146`.

For ground zippers, ObjectHeader shadow scale is BE f32@04, group/texture are
BE s16@32/34, and projection lower/upper height offsets are BE s16@42/44.
The 12-byte entry uses scale@09 and yaw@0A. Shadow half-width/length is
`header.shadowScale * max(scale,10)/64 * 10`. `U8_ANGLE_TO_U16` shifts by **10**
bits (`object_functions.h:12`), so yaw is `angleY * 2π/64`.
Eligible batches exclude HIDDEN0x100, DECAL0x800, WATER0x2000 and NO_SHADOW0x4000.
Triangles must overlap the height range and have a nonvertical plane. Clip their
XZ polygons to the axis-aligned shadow square and interpolate Y on each facet.
UVs rotate with yaw, use the source's width-based `width*16/halfWidth*1.4142`
scale/center, and normalize by `32*width,height`. The highest center-covering
facet supplies the source height-dependent scaling/opacity formula.

The stock fish entry is16 bytes: u16 home-loop radius@08, u8 depth variation@0A,
texture selection@0B, body scale@0C, local Y scale@0D, loop speed@0E and home-loop
yaw@0F. Scale bytes multiply by .01; loop phase advances `speed<<4` per60Hz tick;
home yaw shifts by8. Positions follow `sin(2*phase)*radius, cos(phase)*radius`,
rotated about stored XYZ. Preview starts at the source's deterministic0x4000
initial phase, omits random depth wander and derives the tail phase from traveled
distance. Tail distance is numerically integrated, not a frame-by-frame RNG replay.
Butterfly entry is12 bytes: u16 attraction radius@08, texture/variant@0A and
scale@0B. Idle animFrame advances by one per60Hz tick, or holds120 for variant2;
wing positions use the source's signed16 sine/cosine shifts and absolute rules.

Portrait entry is16 bytes: s16 radius@0A, yaw@0C and player slot@0E.
Scale is `header.scale * max(radius&255,10)/64`; yaw again uses 64 units/turn.
Its angleZ@08 is not applied by the source initializer. Character sample is a
preview choice rather than an invented saved field.

## Explicit limits

- Decals use floating-point facet clipping, a fixed near-distance Y offset of2
  plus GL depth bias, and the source height fade. Camera-distance fade, distance
  offset growth, N64 vertex truncation, dynamic water geometry and shadow lighting
  are not simulated. No eligible face means no floating replacement quad.
- Fish RNG phase/depth changes and split-screen removal are not reproduced.
  Butterfly pursuit, attraction, flight states and racer interactions are not run.
  Preview trigonometry uses floating point rather than reproducing the N64 sine
  lookup rounding and per-frame integer distance accumulation.
- Portrait visibility and per-player character assignment require live racers.
  The toolbar deliberately supplies a labeled sample instead.
- Boost init clears `level_entry` and binds a shared racer effects record. Render
  requires an owner racer, vehicle, character, active boost state and generated
  trail vertices. Its placed entry cannot determine a valid standalone graphic.
- General object shadows, particles, lava/bubbles, weather/lens flares, racer
  assemblies, shields and dynamic spawns remain separate roadmap work. Invisible
  helpers remain gizmos. OBJ exports track geometry as before.

## Verification

Headless checks cover source strip/UV construction, both windings, deterministic
pose/scrub, local scale and character enum, projected slopes/rotation/scale/height
fade, excluded and degenerate faces, out-of-range projection, signed texture IDs,
extracted JSON and image-overlay refresh. All65 stock levels produce finite valid
meshes and all83 distinct ground zippers referenced by those level headers have
eligible projections. The138 object maps contain92 ground zippers,40 fish,
25 butterflies,8 portraits and1 runtime boost. Nine zipper entries are in maps
unreferenced by the65 level headers; this does not establish that no runtime code
uses them. No geometry association is invented for these orphan map entries.

Native Qt/RTX checks cover picking with gizmos hidden, move/property edits and
undo, animation/scrub without GPU resource churn or project changes, PNG texture
GPU readback and undo for each new graphic, all65 level switches, visibility,
transparent edges and screenshot orientation. Old renderer VAOs, VBOs, programs
and textures are deleted after switching to a level without special artwork.
Full suite:721 passed; final native animation check measured about63 FPS on the
RTX4060 with no GL errors. Mouse decal drag, cancellation and one-step undo pass
without replacing the renderer's GL resources. Compileall and normal launch pass.
No sample ROMs or emulator runs were made; gameplay testing belongs to the user.
