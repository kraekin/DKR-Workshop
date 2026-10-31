# Track materials and driving surfaces

Open **Geometry → Materials** in the right inspector. **Geometry → Mesh** keeps
vertex/face editing; Materials focuses on choosing and editing course materials.
The former Materials page under Tools is removed.

## Change one batch

1. Click a visible face in the viewport, or select a batch in the segment tree.
   All faces in that batch are highlighted. The current image, texture ID,
   driving surface and material number appear together above the list.
2. **Focus** frames the selected batch. **Isolate batch** temporarily hides the
   other track batches and object artwork. Turn it off to return to the course;
   existing render-toggle preferences are retained.
3. **Change this batch’s material…** opens a resizable thumbnail picker of the
   course's existing materials. Search texture IDs, material numbers, surface
   names, formats or dimensions, or filter by image size.
4. Choosing a thumbnail previews it on the actual track. Current/Preview images,
   the before/after driving surface and affected face count stay visible.
   UV coordinates retain their stored values.
5. **Apply** commits one undo step. **Cancel**, Escape or closing the picker
   restores the current material without changing the project.

Material numbers are the course's existing slots: each stores a texture reference
and a driving surface. Assigning a different material to one batch changes that
batch's complete face range. Other batches using the old material retain their
assignments. Levels sharing this geometry receive the same edit and are listed.
No per-face batch splitting or automatic creation of new material slots occurs.

## Edit a shared material

**Edit shared material…** opens the larger texture library. Its top selector can
choose any existing course material, including unused materials. The editor shows
how many batches/faces use it and highlights those uses throughout the course.
Batch isolation is temporarily released while this shared editor is open.

Choose a ROM texture thumbnail and/or a **Driving surface**. The combined change
is previewed and committed together as one undo step. This changes every batch
using that material. It changes the course reference, rather than the global
image's pixel data. The selected material's users and shared course geometry
remain explicit in the preview.

**Compatible choices only** hides textures that would change a batch's protected
opaque/translucent rendering pass. Uncheck it to inspect disabled choices and
their explanation. Full byte/layout validation still runs before preview and Apply.
Images load as they become visible, so opening the library does not decode every
ROM texture at once. Thumbnail orientation follows the Texture Browser's PNG
editing convention; renderer/writer pixel rows remain unchanged.

## Edit an image

**Edit texture image…** opens the Texture & Sprite Browser for the batch's current
texture. Its PNG export/import workflow edits shared image pixels and lists known
uses. That can affect other courses and objects using the image. This is separate
from assigning a material to one batch or changing a course material reference.

## Advanced controls

Expand **UVs, colors and rendering** when needed:

- **Rendering:** existing frame offsets and verified flags. Frame = raw offset
  shifted right by two when in range, otherwise frame 0. Unknown bits and batch
  ordering remain protected.
- **UVs:** select faces and apply texture scale or texel offsets. Raw corner UVs
  remain editable as six signed16 integers; 32 units are one texel. The Both sides
  checkbox changes the existing triangle backface bit. It can also affect collision.
- **Colors:** edit stored vertex RGBA or choose a color for selected vertices.
  Colors are shared by every triangle using that stored vertex. The game's R=G=1
  encoding displays gray and uses stored B as alpha.

Advanced edits apply directly through the existing undo history. The material
picker and shared-material window use explicit Preview/Apply drafts. Switching
levels/views, invoking undo/redo or changing the source restores and closes an
unapplied preview. Saving retains a valid draft, but writes only committed data.
A preview never enters project or ROM output. Unrelated refreshes with the same
material context retain the draft.

**Revert this course’s material edits** restores material fields as one undo step;
geometry and minimap edits remain. Save a project and export the ROM normally.

## Source-backed layout and boundaries

All offsets below are within the inflated model and are big-endian. Model
section27 uses index section26; the master LUT remains0xED0E0/base0xED1B0.

| Record | Size | Editable fields |
|---|---:|---|
| LevelModel | 0x4C | Material writer preserves this whole header, including modelSize, minimap fields, offsets and counts. |
| LevelModelSegment | 0x44 | Preserved whole, including opaque batch split. |
| TextureInfo | 8 | u32 ROM texture ID at0, derived width/height/format bytes4..6, s8 surface at7. |
| Vertex | 10 | Stored RGBA bytes6..9; signed16 XYZ remain unchanged. |
| Triangle | 16 | Flags bit0x40 at0; six signed16 UVs at4..15. Indices and other bits stay unchanged. |
| TriangleBatchInfo | 12 | u8 texture slot0, u8 frame offset7, selected u32 flags at8. Offsets, override, miscData and sentinel are protected. |

The writer patches a copy of the complete original inflated entry. A bit mask
rejects edits to every other byte/bit: pointers, counts, BSP/visibility, bounds,
XYZ, indices, serialized collision facets, opaque ranges, unknown data, sentinel
metadata and trailing bytes. It does not reserialize parsed structures.

The original ROM has **55 models** and **1,416 3D texture entries**. Among local
texture slots, **609** have stored dimensions/format metadata differing from the
referenced header. Those stock values are preserved on no-op assignments;
replacement IDs derive metadata from the replacement header, and restoring the
original ID also restores its original metadata. No blanket normalization runs.

`tracks.c` draws separate stored opaque/nonopaque batch ranges. Replacement
texture/slot/Decal edits must retain each batch's prior effective pass. Texture
translucency includes the flags added by `material_init` for RGBA/CI4 render
modes and IA formats. Incompatible assignments are rejected without editing or
reordering anything. Wave, texture-animation, environment-map, pulsing-light and
unknown flags remain protected because their other data is not rebuilt.

Existing slot255 batches survive unchanged. A newly untextured batch is blocked:
although the main collision path checks255, the vertical surface query reads
the slot without that guard. The editor does not introduce that unchecked access.

Supported surface assignments use the local `SurfaceType` enum codes0..18:
Default/road0, Grass1, Sand2, Zip pad3, Stone4, Egg spawn5, Egg1..4=6..9,
Frozen water10, Calm water11, Taj pad12, Snow13, Wavy water14, unknown waterF15,
unknown16, Invisible wall17 and unknown18. Uncertain codes remain named as such;
the collision code establishes vehicle-dependent filtering for17/18. Choosing
a surface changes the stored selection, not compiled traction/sound/slide tables.
Effects depend on vehicle and game state; the viewport previews artwork and
flags, with no simulation of driving physics, shadows, fog, waves or triggers.

Sources inspected locally under `research/Diddy-Kong-Racing`:
`include/structs.h:565/574/601/618/693/737`, `include/enums.h:152`,
`src/textures_sprites.h:41`, `src/textures_sprites.c:1450`,
`src/tracks.c:774/1885/2581/2831/3144`, `src/hasm/collision.c:128` and
`tools/dkr_assets_tool_src/fileTypes/textureInfo.hpp`.

## Projects and export

Project version4 adds explicitly `rare-decoded` model overlays to `asset_edits`,
with original inflated-entry SHA-1 and changed byte offsets. Versions1/2/3 still
load. Model overlays pass the same field/reference/geometry checks during load
as editor operations. Unknown encodings, modified protected fields, unsupported
surfaces/flags and incorrect base hashes are rejected. Minimap/header/topology
editing through this overlay remains disabled.

Only changed model entries are Rare-compressed (LE u32 size +09 + raw DEFLATE),
aligned to16; unchanged compressed entries and table/section tails retain exact
bytes. Model subtable26 and master offsets are rebuilt when spans change, with
the same original-ROM length, padding refusal, checksum and atomic output rules.
The preflight report lists compressed growth and all shared level uses. Object
maps, headers and materials can coexist in one project/export/history.

Verification covers all55 original model identities/legacy metadata, bit-level
write isolation, signed UVs, protected data, pass rejection, model growth and
capacity refusal, mixed-asset project/export round trips, untouched assets and
OBJ/MTL/PNG consistency. Native checks exercise real UV delegates, invalid input,
color overlays, flags, slots, references, surfaces, picking, camera preservation,
undo, project reopening, shared model refresh and OpenGL resource lifetime.
Final gate: **607 tests passed**, application syntax checks pass, and native
material/placement checks pass without OpenGL errors. Steady viewport measured
**62 FPS** on the RTX4060; screenshots were visually reviewed. No sample ROMs
were generated for review or emulator playtests run; game validation is left to
the user. The separate minimap writer and preview are described below;
see MINIMAP_SETTINGS.md. The material tool's byte mask remains unchanged.
