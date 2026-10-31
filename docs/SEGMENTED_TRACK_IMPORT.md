# Segmented custom-track import

Track import supports external MTL/PNG materials and dedicated custom textures;
see [CUSTOM_TRACK_ARTWORK.md](CUSTOM_TRACK_ARTWORK.md). The geometry compiler and
source limits below continue to apply.

Current track exchange (v1.25.5): export XYZ×0.01; Blender import/export Scale1;
suite import multiplier100, game-space offsets0. Both compilers convert once
before rounding/partitioning/collision. Earlier sample files below are unchanged
raw-coordinate assets; use their explicitly stated Scale1.

For scene setup, modeling, UVs and verified Blender OBJ export settings, see
[Making custom DKR tracks in Blender](BLENDER_TRACK_GUIDE.md).

**Geometry → Import OBJ…** now supports larger static meshes. Leave **Automatic**
selected for normal use. It keeps the original single-segment compiler for small
meshes without surface overrides and uses spatial cells for larger meshes or
per-material surface choices. **Spatial segments** forces the new compiler;
**Single segment (≤499)** retains the earlier restricted mode. Choose an explicit
cell size for experiments, or let Automatic select the largest cell size meeting
the local density budget. Build/preview runs on a worker; Cancel closes safely
after the current compile finishes and never applies its result.

Transform and material changes require another **Build preview**. Each material
can use an existing ROM texture slot and either **From slot** or a chosen driving
surface. Different surfaces sharing an image use separate TextureInfo slots,
reusing existing compatible slots or appending duplicates. Original slots remain
present for track controllers. Texture PNG replacement stays in the existing
Texture & Sprite Browser. External MTL/PNG import is not added by this milestone.

The preview reports actual input, rendered and collision-guide counts, segments,
cell size, compressed/runtime sizes, ROM budget and source query limits. Apply is
one undo step. Existing material/minimap/interior geometry editing, project save,
ROM/OBJ export and stock restore remain available. Spatial projects use version10;
original single-segment projects remain version9 compatible.

## Ready-made driving test

Use `artifacts/samples/ancient-lake-segmented-test/ancient-lake-segmented-test.obj`.
Select Ancient Lake, import it with scale1, offsets0, Automatic mode/cell size,
default slot mappings and surfaces **From slot**. Apply, save a separate project
and export your own ROM. The earlier single-segment sample remains untouched.

The new sample has924 input triangles. Clipping produces1,682 rendered faces in
27 segments with1280-unit cells, plus786 hidden collision-normal guides. Runtime
track data needs192,624 of535,040 bytes; the padded compressed entry is34,272 bytes.
Floor coverage is checked under all eight starts and18 stored car checkpoints.
Follow the yellow stripe and test lap completion, AI paths, seams, the hill,
pickups and forward/reverse camera views. Existing scenery may float/intersect
the wider road; object placements and minimap artwork are retained.

## Source limits and the local guarantee

All references are from the matching local decomp; no runtime limits are patched:

| Consumer | Source and bound |
|---|---|
| Collision segment selection | `src/hasm/collision.s:generate_collision_candidates`: first10 XZ box overlaps |
| Collision candidates |500 entries, including one marker per selected segment |
| Search padding | Input XYZ truncated to integer; rectangle padded20 units per side, boxes compared with5 units tolerance |
| Collision grids |8 intervals on X and8 on Z, inclusive endpoints; assembly advances both endpoints on both axes |
| Floor/water segment list | `tracks.c:2121,2495–2545`:8-entry array, returns no result at count≥8 |
| Rendering segment IDs | `tracks.c:31,1728–1764`:128-entry order/visibility arrays, with visibility index `segment+1`; cap127 segments |
| Static draw commands | `tracks.c:1940–1980`, `textures_sprites.c:695–850`: conservative8 commands per batch; `thread3_main.c:85` one-player frame pool4500 |
| Runtime track heap | `tracks.c:30,2832–2920`:0x82A00 bytes including regenerated grids, planes and aligned water-index data |

The NON_MATCHING C transcription of `compute_grid_overlap_mask` has an incorrect
Z loop. The shipped handwritten assembly is authoritative and advances the
lower/upper Z endpoints, just as for X. The query model follows that assembly.

Each occupied cell has at most120 ordinary collidable faces. Cell boxes overlap
their ideal boundary by one unit, and cell size is at least512 units. For raw
query X and Z spans no greater than **cell size−56** before game padding, the
padded/toleranced rectangle intersects at most two columns × two rows. This
bounds selection to4 segments and4×(120+1)=484 candidate entries, below500, even
without grid filtering. Float-to-integer truncation and inclusive endpoints are
included in the margin. A point's floor lookup intersects at most4 cells, below
the eight-entry list's rejection threshold. Tests exercise boundary-aligned,
negative-coordinate and random query rectangles with the source grid filter.

This guarantee is local. Long camera sweeps, large shadows, teleports or other
queries spanning more than the reported envelope can still reach the game's
10-segment/500-entry truncation. The game already has those limits; segmentation
alone cannot remove them. Performance and the shared whole-frame command pool
also depend on objects, HUD, effects and player count. The report's static track
command bound is not a whole-scene performance or allocation guarantee.

## Generated geometry and seams

The compiler quantizes the transformed input to signed16 and validates triangle
orientation/manifold edges. It clips into a uniform XZ grid, caches rounded edge
intersections across shared geometry and interpolates UVs/colors. Convex ear
triangulation retains boundary points, avoiding extra gaps at cell junctions.
Each cell's batches retain24-vertex/16-face source-compatible limits and opaque-before-
translucent ordering. A balanced X/Z BSP orders the occupied cells.

Serialized8-byte facet records reference local base/neighbor planes. For an edge
crossing a segment seam, the neighboring triangle is copied as a **collision
normal guide** in that segment. Its batch is Hidden + No collision, with a real
non-water texture slot. It contributes a base normal to the source's runtime
edge-plane builder and does not draw, collide, affect floor height or export as
ordinary OBJ geometry. Helper positions and graph links are validated against
the actual neighboring segment faces; reciprocal edge planes are checked across
seams. This preserves smoothing across slope changes and sharp shared edges.

Guide flags and water surface exceptions are protected. Guide XYZ groups remain
locked during local geometry editing; reimport the authored mesh to reshape
these seams. Interior geometry can still be edited inside its cell/BSP envelope.
Material and minimap edits retain their separate undo/revert paths.

Every PVS row initially marks all segments potentially visible. The game still
applies its per-segment frustum test. This conservative visibility avoids guessed
occlusion/popping; no occlusion optimizer is claimed. Original objects/checkpoints,
AI/cinematic paths, minimap artwork, headers and wave settings are not retargeted.
New animated wave geometry, new level IDs and save-slot expansion remain separate.

## Bounds, persistence and verification

Input is bounded to6000 triangles,4 MiB and20,000 OBJ vertices; output is bounded
to6000 stored triangles including clipping/guides and127 segments. The runtime
heap, signed16 grid arithmetic, material slots, batch limits, canonical layout,
BSP coverage, PVS offsets, collision graphs and generated planes are validated.
Dense cells are refused even if total triangle count is modest. Automatic tries
smaller available cells before refusing density/segment limits.

Segmented compression retains an additional16-byte lookahead block after its
aligned Rare DEFLATE stream. One all-template test exposed a transient staging
stream whose aligned end had insufficient inflater lookahead. Temporary per-cell
records are not exported; the assembled track is audited with its final padded
stream and fixed-heap staging. Preview and the production ROM writer use the same
compressor, preserving exact budget/assembly agreement.

Version10 stores canonical baseline/current buffers and original asset hashes.
Version9 cannot load segmented baselines; legacy writer permissions remain intact.
Failed previews and rejected imports preserve project/history/output. Normal ROM
assembly remains bounded to original ROM storage, updates checksums and preserves
unrelated entries/sections. No emulator or user-review ROM is generated by these
checks. See [PROJECT_FORMAT.md](PROJECT_FORMAT.md).

Automated checks cover larger meshes, all55 original templates, BSP/PVS, sharp
cuts, source query bounds, reciprocal seam planes, floor continuity, tamper/budget
refusals, protected guide/interior editing, v10 history/reopen and in-memory ROM/
OBJ export. Native checks cover the real chooser, responsive worker, material
surfaces, failure/cancel, Apply/GPU undo/redo, sprites, interior XYZ editing, stock
restore, narrow inspector and clean OpenGL. User gameplay review is required for
seams, collision, cameras, race completion and performance before further scope.

Verification gate:1,204 full tests passed in309.28s, including74 segmented-import
checks. Native RTX4060 OpenGL3.3 checks passed. Original Rev1 ROM SHA-1 remains
`6d96743d46f8c0cd0edb0ec5600b003c89b93755`.

User gameplay review, 2026-10-20: the segmented sample was played through to race
completion, with no reported issues. The representative segmented-track gameplay gate
is complete. This verifies the tested sample without changing the compiler's
source-based limits or authorizing a new milestone.
