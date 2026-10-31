# Editing roadmap after v1.4.0

Planned 2026-10-19 from [FEATURE_AUDIT.md](FEATURE_AUDIT.md), with object
creation/duplication/deletion deferred at the user's request. Phases 0–19 have
passed automated/native checks; gameplay verification is performed by the user.
Phase20's audit/foundation checks pass, but its full structural safety gate is open.
Phase 12 evidence is in [PLACEMENT_TOOLS.md](PLACEMENT_TOOLS.md); Phase 13 is in
[ROUTE_RESEARCH.md](ROUTE_RESEARCH.md). Phase14 implementation/evidence is in
[TRACK_MATERIALS.md](TRACK_MATERIALS.md). Phase15 is documented in
[MINIMAP_SETTINGS.md](MINIMAP_SETTINGS.md). Phase16 is documented in
[IMAGE_ASSETS.md](IMAGE_ASSETS.md). v1.9.1 includes the image browser, symmetric
3D PNG export/reimport and protected image/anchor/timing overlays;700 headless tests
and native image/material/minimap checks pass on the RTX4060. No sample ROMs are
generated for review; the user owns gameplay tests, including pending minimap
tests. Phase17 special artwork is implemented in v1.10.0; see
[SPECIAL_ARTWORK.md](SPECIAL_ARTWORK.md). Phase18 environment preview is documented
in [ENVIRONMENT_PREVIEW.md](ENVIRONMENT_PREVIEW.md); Phase19 cinematic paths and
existing-node edits are in [CINEMATIC_PATHS.md](CINEMATIC_PATHS.md). v1.12.0 passes
752 headless tests. The compact toolbar follow-up shares Special art/environment
on one row. Phase20's audit and isolated headless structural foundation are
implemented in v1.13.0; see [STRUCTURAL_SAFEGUARDS.md](STRUCTURAL_SAFEGUARDS.md).
The v1.13.1 follow-up adds per-stream source-model inflate checks, a58-placement
decoration research subset and read-only RDRAM/BizHawk2.10 state measurements;
see [RUNTIME_CAPACITY.md](RUNTIME_CAPACITY.md). Production structural operations
were subsequently enabled in Phase21 with source bounds and representative
user gameplay reviews. Phases22–24 added geometry editing, segmented custom
track import and dedicated artwork; their representative gameplay gates passed.
The user brought course-building helpers forward as25, then deferred autosave,
crash recovery and project backups again. Course names are now explicitly
authorized in a separate window/menu; dialogue/menu text is excluded. Current
evidence is below and in STATUS.md.
Complete one phase, record its evidence in compact STATUS.md, then stop after
the last authorized phase. Authorization for one phase does not authorize
subsequent phases.

## ROM space and object safety

Each map does **not** need to stay inside its original compressed span. Existing
position/property edits can already change compressed size. The writer rebuilds
the map index and master offsets, relocates later asset sections and updates N64
checksums. It writes a new ROM and refuses growth beyond available original-ROM
padding. Existing tests cover a real map growing 16 bytes and relocation of all
later sections (`test_real_slot_growth_relocates_assets_and_preserves_rom_tail`
in `tests/test_editing.py`).

A read-only check of the original USA Rev 1 ROM on 2026-10-19 found:

| Quantity | Value |
|---|---|
|Original ROM length|0xC00000 = 12,582,912 bytes|
|End of the 50 asset sections|0xB8CFD0|
|Contiguous trailing padding accepted by the current writer|471,088 bytes, approximately 460 KiB|
|Original SHA-1|6d96743d46f8c0cd0edb0ec5600b003c89b93755|

This is a shared **compressed-asset growth budget**, not extra runtime RAM or a
guarantee that every larger asset will load. Arbitrary ROM expansion is outside
this plan. Keep the original-ROM length and padding/overwrite refusal.

The authoritative local `src/objects.c:44–48` defines a 0x3000-byte map allocation,
a 0x15800-byte object pool and 512 object slots. Map loading at 978–997 also stages
compressed input within its workspace. Derive safe bounds from the entire loader;
do not treat 0x3000 as an allowed entry-payload size. Dynamically spawned actors,
attachments and behavior-specific allocations also consume resources, so 512
placed entries is not a proven safe allowance.

Phase20 derives the necessary staging constraints as `U + 32 <= 0x3000` and
`C <= U + 32`, where U includes the decoded header/alignment and C is the stored
table span. Shared object headers also occupy the object pool. These checks and
baseline counts do not certify peak memory or overlapping inflate safety.

References, unique indexes, ordering and shared maps are additional constraints.
Deleting a linked checkpoint can break a course despite reducing its byte count.
Existing projects identify entries by map/index and base-entry hashes; insertion
and deletion require stable identities, structural undo and project migration.
Phase20's separate research draft prototypes stable identities/history and
v1–6 project imports; production projects remain version6 with their existing
entry writer. Unknown bytes must survive. Duplicating bytes is straightforward; a dependable
editor feature needs the later feasibility gate. Equal-size replacement alone
would not resolve runtime resources or references.

## Common verification gates

- Inspect the local decomp before each parser/writer. Preserve unknown fields,
  unsupported values and untouched assets. Distinguish serialized data from
  runtime pointers and compiled constants. Retain the single `src/` layout.
- Retain base-ROM identity/overwrite protections, atomic saves, undo/redo,
  compatibility with old projects and headless core modules.
- New writers need byte-level edit/undo/project/export/reload tests, unchanged
  asset comparisons, bounds/malformed-input tests and capacity failures that
  preserve existing output. Run the full pytest suite for code changes.
- Verify affected Qt interactions and native OpenGL behavior. Preview-only
  controls must not dirty projects or imply unsupported game simulation.
- Separate automated results from actual game tests. Test gameplay changes
  in-game before claiming their behavior works; record pending game validation
  explicitly at review. Update STATUS.md and stop after each phase.

## Main milestones

### Phase 10 — Export budgets and project foundation

Show current/projected compressed asset usage, remaining padding, changed assets
and shared dependencies. Extend versioned projects/history for later asset
writers while retaining old object projects. Add a readable project diff and
pre-export report. No new asset editing or structural object operations.

**Gate:** Old projects reopen identically; no-edit ROM identity and existing map
exports pass. Verify relocation/alignment, capacity boundaries, report accuracy
and rejection before publishing output. Reports do not dirty a project. Future
asset writers remain disabled.

### Phase 11 — Level settings

Edit verified fixed LevelHeader fields: laps, default/allowed vehicles,
checkpoint sets, established AI difficulty, fog/background, camera defaults,
existing skybox/music references and verified weather settings. Preserve the
serialized 0xC8 record and unknown tail. Keep geometry/map reassignment and
progression-sensitive world/race changes read-only pending dependency validation.
Names are a separate milestone below.

**Gate:** Field-byte isolation, ranges/references, undo and old/new project/ROM
round trips; native inspector/preview checks where supported. Record representative
in-game laps, vehicles and music/environment checks. No object count changes.

### Phase 12 — Placement tools for existing objects

Multi-selection, grouped moves/property edits, schema-aware rotation/scale
handles, terrain drop/snap, alignment and orthographic views. Expose transforms
only when stored by that entry type. Copying property/position values is allowed;
pasting new object entries remains deferred.

**Gate:** One undo per gesture/group, cancel/focus-loss, mixed types, signed
limits, terrain-hit math, camera-speed regression and saved-byte accuracy.
Object IDs, entry lengths and counts stay unchanged.

### Phase 13 — Existing route tools and research workflow

Edit existing checkpoint lanes and AI connections visually, with index/vehicle/
alternate-route labels and graph diagnostics. Add per-field notes, known/unknown/
unused descriptions and saved experiment comparisons. Preserve source keys and
raw editing. No node insertion/removal or silent reference renumbering.

**Gate:** Only intended existing fields change; valid links survive and dangling/
duplicate references are identified. Verify undo, notes/project round trips and
a representative in-game checkpoint/lane experiment.

### Phase 14 — Track materials and driving surfaces

Write existing LevelModel texture references, per-corner UVs, vertex colors and
verified render flags. Expose verified TextureInfo surfaces such as road/grass/
ice and shared material uses. Preserve geometry/collision data and all counts.
Surface assignment does not edit compiled global traction/slide response tables.

**Gate:** No-edit model identity, offsets/signed UVs, unchanged geometry/assets,
OBJ/MTL consistency and GL preview. Confirm changed driving behavior in-game.

Implemented in v1.7.0; automated/native gate passed (607 tests). Gameplay gate
is performed by the user. Existing opaque/nonopaque ranges are protected;
incompatible texture/Decal pass changes and new slot255 assignments are blocked.
Preserve legacy slot metadata, serialized collision arrays and unknown bits.
See TRACK_MATERIALS.md for the verified fields and preview limitations.

### Phase 15 — Minimap settings

Edit existing sprite references, rotation, scale, Adventure1/2 offsets and tint,
with a preview using source coordinate conventions. No topology changes; custom
minimap images use Phase 16's image writer.

**Gate:** Field isolation, references/units, project/ROM round trips, preview
orientation and representative in-game map placement.

Implemented in v1.8.0; automated/native checks passed (643 headless tests).
Tools → Minimap previews drafts; Apply stores one undo step. Sprite references,
degree rotation, finite float32 marker scales, signed offsets and RGB tint use
a protected model-header whitelist. Adventure2 mirroring follows the source's
sprite anchor and separate marker offsets. Version5 projects read versions1–4;
material/minimap reverts are independent. User game placement/tint checks remain
pending. See MINIMAP_SETTINGS.md for source equations and preview limitations.

### Phase 16 — Texture and sprite replacement

Asset browser with thumbnails/use lists and PNG export/reimport. Start at existing
dimensions, pixel format and frame count using verified encodings; expose
existing sprite anchor/timing fields where understood. Keep IDs/table counts.
Same dimensions do not imply equal compressed size; use the export budget.
New dimensions/formats/palettes and longer sequences need another scoped gate.

**Gate:** Encoder/decoder checks including expected quantization, alpha, row
swaps and frame bounds; no-edit identity/shared-use reports. Reload exports and
verify representative track/sprite images in GL and in-game.

Implemented in v1.9.0;689 headless tests and native checks passed.
Edit → Texture & Sprite Browser / PNG covers all 2,332
texture entries and 193 sprites. Existing frames export to PNG and reimport with
a staged N64 quantization preview. Fixed tile layouts, shared IDs, original
headers/tails and frame counts are preserved; multi-tile imports are one undo.
Sprite anchors are verified; sprite definitions have no speed field. Texture
timing is exposed as raw counter advance. Version6 projects read versions1–5;
tables3/5/13, relocation and budget protections cover image writes. Native checks
read track/sprite texels back from the GPU, including minimap artwork and project
reopening. New dimensions/formats/palettes/frame counts remain deferred.
See IMAGE_ASSETS.md; gameplay checks remain with the user.

Phase16 follow-up v1.9.1 adds symmetric 3D PNG orientation matching the local
extractor, upright browser previews/thumbnails, PNG orientation metadata and a
legacy raw mode. Stored rows, UVs, project format and 2D/sprite behavior remain
unchanged. Full suite:700 passed; native sign186 preview/export/inverse import,
GPU row placement, metadata/legacy mode and image workflow checks passed.
This follow-up does not start Phase17.

### Phase 17 — Remaining physical object artwork

Ground zippers through the verified projected decal/shadow path, then verified
procedural fish/butterflies and applicable portraits/boost art. Keep invisible
helpers as gizmos and label runtime-dependent graphics. Preview only.

**Gate:** Placement, depth/alpha/orientation, animation, picking and edits remain
correct; no GL leaks/errors or preview-induced project dirtiness. List graphics
unresolved from static level data.

Implemented in v1.10.0: source-sized ground zippers clip/project to track facets;
fish home loops/tails and idle butterfly wings share play/pause/scrub; portraits
offer an explicit character sample. Special art visibility is independent of
gizmos/models/billboards. Artwork follows position/property/image edits and undo.
721 headless tests pass, covering all65 levels and their83 placed zipper projections; native
RTX checks cover picking, editing, texture GPU readback, level switches and resource
deletion without preview dirtiness. Boost remains a labeled runtime helper:
the source attaches it to a live racer and generates trail geometry, so static
placement data cannot supply an applicable mesh. Other runtime limits and precise
source references are in SPECIAL_ARTWORK.md. No writer/project format changes.
Phase17 passed its gate before Phase18; gameplay checks remain with the user.

### Phase 18 — Environment preview

Source-backed skybox/fog/background, animated/scrolling track textures and water
preview. Earlier writers handle supported stored edits. Full particles, weather/
lens flares, game lighting/shadows and vehicle assemblies remain separate
optional work; this phase does not silently include all special renderers.

**Gate:** Timing/units, deterministic pause/scrub, level switching, edited-default
refresh, GL resources/performance and unchanged saved bytes for preview controls.
Document approximations.

Implemented in v1.11.0. Source sky/background and perspective fog, track frame
modes and per-controller scrolling, plus a labeled approximate two-texture wave
preview share the existing timeline. Preview controls leave project bytes/history
unchanged and existing header/image/object edits refresh their inputs. Full suite
735 passed, then all15 environment tests passed after the final scroll-fraction
case. Native checks passed across65 levels, about63FPS, persistent GL resources,
GPU wave/UV buffers and saved-default refresh. See ENVIRONMENT_PREVIEW.md for
source offsets, units and limits. Phase18 passed its gate before Phase19.
User-requested follow-up merges Environment into the Special art row, right
aligns its controls and reduces toolbar padding. Native normal/narrow layout,
controls and GL checks pass; no preview state enters the project.

### Phase 19 — Cinematic and actor paths

Draw existing Animation/camera paths; preview verified position, rotation and
timing. Edit existing-node fields with timeline feedback. Show understood event
markers without claiming a full game-state simulation. New nodes wait for
Phase 21 and their own validated schemas/references.

**Gate:** Ordering/channel/loop/interpolation, deterministic scrub, actor versus
camera paths, save/undo and an in-game edited-path example. List unsupported events.

Implemented in v1.12.0: Tools → Cinematics groups existing scene/ambient actors,
draws colored actor/camera paths, samples NTSC delays/speed/pauses/interpolation/
loops/clip modes and offers existing-node fields with arrival/event feedback.
Optional camera view includes roll and restores the free camera. Runtime waits,
scene changes, live substitutions and unsupported script/vehicle effects are
explicitly labeled. No nodes or project schema/writer permissions are added.
752 headless tests and native checks of all65 levels/263 scene choices,
edit/project/undo, scrub/camera restoration and resource reuse pass; see
CINEMATIC_PATHS.md and current STATUS.md. The user's in-game edited-path check
remains pending. Phase19 preceded the authorized Phase20 feasibility work.

### Phase 20 — Structural object feasibility and safeguards

Audit map workspace, pool usage, dynamic-spawn headroom, templates, references
and shared maps for a conservative set of ordinary objects. Design stable
project identities, structural history and deterministic map rebuilding with
correct payload length/alignment. No creation/deletion/type-conversion UI.

**Gate:** Headless append/remove/reorder, reference checks, old-project migration,
unknown/reserved-byte preservation, capacity rejection and exact undo/export
reload. Test conservative experimental ROMs in-game before UI enablement. Record
established types and resource bounds; keep operations/types with unresolved
required bounds disabled. An incomplete estimate is not a safety guarantee.

Audit/foundation implemented in v1.13.0; full safety gate remains open:
read-only File budget → Object capacity audit; isolated
stable-identity structural drafts, template provenance, structural history,
deterministic rebuilding and v1–6 project import. Headless append/remove/reorder,
protected graph/reference checks, unknown-byte preservation, atomic capacity
failure, undo and in-memory export reload pass. All138 maps satisfy the checked
staging address bounds; the tightest leaves1816 bytes. Only206 simple scenery
placements meet the narrow exact-object-block template audit. No dynamic reserve
or safe additional-object count is proven. Production operations remain disabled;
no structural UI/new production project version was added. 778 headless tests
and native report/copy/editor/toolbar checks pass. See STRUCTURAL_SAFEGUARDS.md.
User in-game checks are pending before any Phase21 UI enablement; no review ROMs
or emulator runs were generated. Stop before Phase21.

The authorized v1.13.1 follow-up checks Huffman heap/lookahead, output bounds and
unread-input overlap for each modified stream, with game-unsafe stored/incomplete
trees refused. All136 original/recompressed maps and58 narrower decoration
append/remove streams pass the source model. File budget → Runtime measurements
reads raw RDRAM or the inspected BizHawk2.10 Mupen carrier and compares observed
list/pool/cache/reference counts without editing a project. Two existing Central
Area snapshots show22,864–23,184 free object-pool bytes, not guaranteed reserves.
An optional user-run Lua capture helper is read-only. No production structural
type/operation is approved; peak/runtime/reference and representative game gates
are still open. Full821 tests pass, with final43 inflater/runtime/Lua checks
rerun and native real-snapshot/editor checks. This is continued Phase20 research,
not Phase21 UI completion.

Lua loader follow-up: BizHawk reports loaded code as [string "main"], so the
capture helper uses an explicit project artifacts directory rather than Lua
debug source paths. Regression checks cover file/main/=main chunks with all
three bulk-read APIs. No game execution or structural permissions are added.
Full suite after this fix:827 passed in87.69s; all9 Lua regressions pass.

Subsequent user capture review: six distinct Ancient Lake (map roles5/73) raw
snapshots validate. Observed list peak192/512; object-pool minimum free33,696 B,
largest block31,632 B; descriptor peak228/512. This completes the initial
baseline collection, not the operation/type safety or edited-gameplay gate.
The narrow palm-top candidate assets are absent from these samples; same-map
bush collision/shadow-texture references need their own check. See
RUNTIME_CAPACITY.md and the ignored per-capture evidence. No Phase21 controls
or additional production writer permissions were enabled.

The authorized v1.13.2 one-bush experiment audits Ancient Lake's existing solid
BlueBerryBush (map5/entry4, header43/sprite108):208 B aligned block plus one
list/interaction/header/sprite/2D shadow-texture9 reference. It has no emitters,
attachments or lights. Also found:257 interactive pointers in a separate stack
array and fixed400-record/800-triangle/2000-vertex shadow buffers. Their future
peaks remain outside the observed baseline. A restricted user-run command
previews in memory or explicitly exports exactly one clone, validates resident
baseline assets, rebuild/reload/CRC/untouched bytes and refuses existing outputs.
No project migration or Phase21 controls. User fresh-load/collision/restart/
re-entry gameplay and new captures are next; see BUSH_EXPERIMENT.md.
Verification:853 headless tests pass in92.94s, including26 one-bush regressions;
real six-capture CLI preview and compileall pass. No review ROM was generated
outside temporary tests and no emulator was launched. Stop for user gameplay.

### Phase 21 — Conservative object creation, duplication and deletion

The user explicitly expanded this milestone after the successful one-bush test:
all object types are to be available so they can test gameplay themselves.
The earlier bush-only/type/reference gates are superseded. Enable experimental
add/duplicate/delete for all304 valid translated IDs. Prefer actual stock
placement templates; expose clearly labelled zeroed source-schema defaults for
unplaced types. Preserve raw parameters and copied graph IDs/links, display
diagnostics and shared map uses, and leave graph repair/renumbering to explicit
property edits. Keep hard serialization/workspace/ROM/minimum resource bounds.
Do not label every type or a universal dynamic reserve as gameplay-proven.

**Gate:** Native palette/add/duplicate/delete, selection/filter stability, one-step
undo, project reopen, rebuilt maps/checksums and representative user game tests.
Exercise rejected edits/failed exports. Retain original-ROM length/protections.

Phase20 gameplay evidence: the user reports the exported one-bush ROM worked,
with an in-game screenshot. Three additional Ancient Lake snapshots have the
exact expected map5 bytes, all3 bush positions/208-byte blocks and header43/
sprite108 references3. The exported ROM hash matches the prepared experiment.
This establishes the tested operation; the user's explicit broader scope is
the authorization for other types, rather than extrapolated safety evidence.

Implemented in v1.14.0: Objects Add palette304 IDs, preferred stock templates/
explicit zeroed defaults, target map/XYZ/shared uses, multi-selection duplicate
and delete, one-step undo/redo, stable editor IDs separate from serialized order,
notes/provenance and strict v7 structural project rows. Versions1–6 remain
readable; unchanged structure saves v6. Graph IDs/links are retained with
nonblocking diagnostics, not silently repaired. Known bounds/refusals and
untouched ROM protections remain. Full875 tests pass in133.79s; final32 affected
graph/report/runtime checks pass after wording/diagnostic updates. Native real
palette/buttons/Ctrl+D/filter/selection/graph/history/project/failed-export and
RTX GL3.3 checks pass with four toolbar rows. Subsequent user gameplay review
confirms the preview correction and four added Central Area trees. This closes
the representative Phase21 review; arbitrary type/graph testing remains
experimental. That review cleared the way for Phase22.

v1.14.1 corrects a Phase21 preview bug: additions/deletions can shift cinematic
nodes' flattened viewport indices while retaining their stable editor IDs.
Refresh the animation cache when those indices change, preventing a camera
pose from moving existing scenery (the RubberTree/BeachTree report). Serialized
object data and project format are unchanged. All878 tests pass in129.46s;
native RTX GL3.3 artwork/history/project/in-memory export checks pass.
Phase21 user review, 2026-10-20: the new raw Lua snapshot validates against
Rev1 and contains map0 unchanged (209 entries) and map68 with its original88
entries unchanged plus exactly four RubberTrees (92 entries). The user reports
seeing all four in-game with no other observed issues. Captured list265/512;
object-pool free22,224 B, largest free block15,824 B. These are observations of
this test, not a universal capacity allowance. Evidence is under ignored
artifacts/phase21-central-area-capture.json and the capture's .audit.txt.
That review completed the representative Phase21 gate. Phase22 follows below.

### Phase 22 — Editing existing track geometry

Constrained vertex/face edits with unchanged topology/counts. Verify serialized
collision facets and update affected bounds/data; account for BSP/visibility,
restricting edits when dependencies cannot yet be rebuilt. Generated collision
planes are runtime data, not ROM arrays. Phase 14 already provides material/color
editing.

**Gate:** No-edit identity, derived-data consistency, valid batches/segments/
collision, resource limits, export/reload and GL checks. In-game drive/collision
tests precede claims that edited road geometry works.

Implemented scope in v1.15.0: Tools → Geometry selects existing vertices/faces,
moves XYZ by numeric/nudge or viewport gizmo, and links coincident original
positions across batches/segment seams. Rejected moves preserve state; mouse
previews cancel or commit one undo step. Geometry/material/minimap reverts are
independent. Version8 stores geometry alongside optional structural rows;
versions1–7 retain their earlier permissions. ROM/OBJ export and shared-use/
XYZ reporting are integrated.

All55 source profiles verify8-byte facet links, BSP leaves and runtime heap
allocations. Original segment boxes/BSP/PVS/model bounds form the fixed spatial
envelope, rather than being expanded/recompiled in this milestone. Water and
unresolved stock smoothing-link vertices stay protected. Float32 plane collapse,
orientation changes, unwelding/merging, partition crossing and signed16 overflow
are refused. Runtime grids/planes regenerate in-game from retained topology.
Stock PVS occlusion/self-intersections are not comprehensively recomputed; user
drive/collision/visibility tests are still required. See
[GEOMETRY_EDITING.md](GEOMETRY_EDITING.md). Phase23 was unstarted at that gate;
its subsequently authorized stages are recorded below.

Verification gate:947 full tests passed in162.89s after final preview/picking
changes (69 new geometry tests). Native RTX4060 GL3.3 checks pass real face/
corner picking, numeric Enter (one commit), nudge/refusal, GPU positions,
mouse drag/undo/Esc, face movement, v8 reopen and four toolbar rows. Normal
`python -m src.main` launches cleanly with depth24/4x widget MSAA. Existing
user windows were preserved. Implementation is ready for user driving tests;
no emulator or persistent sample ROM was generated. Work stopped for Phase22
review before the later Phase23 authorization.

Phase22 usability follow-up, v1.15.1: Geometry is now a main inspector tab and
Research is removed from Tools (existing project notes remain compatible).
Compact XYZ/nudge controls and bounded combo sizing reduce the native inspector
minimum from560 to306 pixels. Geometry's Edit face material shortcut opens the
face's batch slot on Materials → Faces, with the affected face count and a slot
texture/surface shortcut. The user confirmed batch assignments meet their needs;
no independent-face batch splitting is required.

Title: DKR Editing Suite - v1.15.1, plus the unsaved-change indicator. Persistent
status: one GPU name, FPS, XYZ/FOV and ROM budget. Full driver details stay in Help.
Inline editor padding previously left zero text height in16-pixel property rows;
compact item-view styling plus explicit foreground/selection colors fixes it.

Follow-up verification:947 tests passed in239.25s; isolated RTX4060 GL3.3 checks
cover all narrow inspector pages, real batch selection and single-byte changes,
undo/redo/project reopening, geometry picking/drag/escape/GPU positions and
readable double-click editors for object numbers, named choices, geometry XYZ,
UVs, RGBA and saved level settings. Selected glyph pixels and complete16-pixel
text contents are verified; commit/undo/cancel and search styling remain intact.
Screenshots reviewed. No Phase23 work or agent-run emulator tests were started.

User gameplay review, 2026-10-20: Ancient Lake geometry edits worked in-game,
including collision, with no reported breakage. The representative Phase22
gameplay gate is complete for the supported constrained geometry edits. Phase23
had not started at that review; the subsequent23A milestone is recorded below.

### Phase 23 — Custom geometry import and track rebuilding

Importer/compiler for topology, segments, batches, serialized collision facets,
visibility/BSP and memory constraints. Replace an existing track first; new level
IDs/save slots are a separate code project. The local tool's raw LevelModel
pass-through is not a completed track compiler.

**Gate:** Rebuild stock examples without functional changes, then import a small
custom track. Validate derived data/dependencies, ROM/RAM budgets, rendering,
collision and actual racing. Failed imports preserve existing projects/output.

The user selected these stages, initially authorizing **23A** on2026-10-20:

**23A — Stock-track rebuild foundation.** Reconstruct unchanged original track
records and retain unsupported bytes, serialized collision links, stock bounds,
BSP and visibility exactly. Check normal/cutscene runtime generation, compression
and combined ROM budgets. Expose selected/all-stock verification and explicit
user export, preserving the open project. Automated no-change reconstruction
and export checks precede the user's stock gameplay comparison. This stage is
complete following the gameplay review below.23B follows its own authorization.

**23B — Small custom-track import.** Implement the missing compiler stages for
new topology and dependencies, then replace one existing track with a small
custom model. Verify rendering, collision, racing and ROM/RAM limits before
expanding scope. The user authorized this after23A review, as recorded below.

**23C — Broader import support.** Larger layouts, multiple segments, material
workflows and useful resource diagnostics after the small-track compiler works.
Additional level/save slots remain a separate project.

23A is implemented in v1.16.0; see [STOCK_TRACK_REBUILD.md](STOCK_TRACK_REBUILD.md).
Verification:1,025 full tests passed in158.85s (78 stock-rebuild tests), with
headless all55 record identity, runtime branches/derived data, recompression,
combined budget refusal, unchanged sections/entries, CRC and failure isolation.
Native RTX4060 GL3.3 checks pass selected/all55 worker runs, responsive rendering,
Stop/close, copy/cancel export, a narrow inspector and preservation of unsaved
geometry/history. Screenshots reviewed. Automated ROM assembly stayed in memory;
the user can explicitly export a stock rebuild for gameplay comparison.

User gameplay review, 2026-10-20: exported stock rebuild tested in Central Area
and three early tracks, all working with no reported issues. The representative
23A gameplay gate is complete. The user subsequently authorized23B by asking
to proceed, and continued the interrupted turn.

23B is implemented in v1.17.0; see [CUSTOM_TRACK_IMPORT.md](CUSTOM_TRACK_IMPORT.md).
The OBJ compiler builds one static segment, at most499 triangles, welded collision
neighbors, bounds and self PVS with no BSP nodes. The collision bound comes from
the500-entry runtime candidate array (including a segment marker), rather than
assuming ROM padding provides runtime capacity. Batches retain existing texture
slots and obey source microcode limits. A separate GL preview supports transforms,
material mapping and existing object/path overlays. Apply/undo/redo/stock restore,
v9 project reopening, existing geometry/material/minimap editors and normal ROM/
OBJ exports are integrated. Failed previews/imports preserve the current project.
The user reviews collision, racing and visibility before23C. No automatic
retargeting of objects/paths, new wave geometry, new level IDs or broader segmented
compiler is included.

Verification gate:1,130 full tests passed in191.76s, including105 import tests.
Native RTX4060 GL3.3 checks passed actual file chooser/preview/Apply, rejected
preview and cancellation preserving unsaved work, high-segment selection reset,
GPU topology refresh through undo/redo, imported XYZ editing, v9 reopen and stock
restore. Screenshots reviewed; no emulator or persistent sample ROM was generated.
User gameplay review: the supplied 462-triangle sample replaced Ancient Lake
successfully and the user completed the race with no reported issues. The
representative23B gameplay gate is complete. The user subsequently authorized23C.

23C is implemented in v1.18.0; see
[SEGMENTED_TRACK_IMPORT.md](SEGMENTED_TRACK_IMPORT.md). Automatic imports retain
the single-segment compiler for small meshes and use uniform XZ clipping for
larger meshes or per-material driving surfaces. The spatial compiler builds
balanced BSP ordering, conservative PVS and protected collision-normal guides
across segment seams. A responsive worker previews the result before one-step
Apply. Version10 projects preserve segmented baselines; version9 and earlier
retain their original permissions. OBJ export omits collision guides.

Bounds:6,000 input/stored triangles including guides,127 segments,120 ordinary
faces per cell and the original0x82A00 track heap. Source collision selection is
limited to10 segments and500 candidate entries including segment markers. For
query X/Z spans at most cell size minus56 before game padding, the compiler
certifies at most4 segments /484 entries; point floor overlap is at most4.
Longer sweeps and shared frame-command/performance budgets remain gameplay
concerns. No runtime limits or level/save-slot counts are patched.

The new924-input-triangle Ancient Lake sample compiles into27 segments with
1,682 rendered faces and786 hidden normal guides, using192,624 B runtime.
Its eight starts and18 car checkpoints have checked floor coverage. The user
performs its seam/collision/camera/race/performance review after automated and
native gates; no emulator or persistent review ROM is generated automatically.

Verification:1,204 full tests passed in309.28s, including74 segmented-import
tests and all55 stock target templates. Native RTX4060 GL3.3 checks passed the
actual chooser, responsive worker, material surfaces, rejected/cancelled preview,
Apply/GPU/history, retained sprites, interior geometry edits, v10 reopen,
helper-free OBJ export, stock restore and narrow inspector. Original ROM hash
is unchanged.

User gameplay review, 2026-10-20: the user played the segmented Ancient Lake
sample, completed the race and reported no observed issues. This completes the
representative23C gameplay gate and the planned23A/23B/23C sequence. The source
limits above remain enforced. Wait for the user to select and authorize another
milestone; no independent milestone has started.

### Phase 24 — Custom-track materials and textures (complete)

The user selected this on 2026-10-20 after the successful23C segmented race.
Read local objModel.cpp/buildTexture.cpp, TextureHeader/TextureInfo and the
runtime texture table/cache/loader/material commands first. Add staged OBJ/MTL/
PNG import, N64 conversion previews, dimensions/alpha/wrapping and driving
surfaces. Append dedicated static 3D texture assets with stable existing IDs
when source bounds permit, preserving stock artwork. Existing PNG replacement
remains available. Use one atomic track/artwork undo step and self-contained
versioned projects; older project writer permissions must remain intact.

Gate: malformed/missing sidecars, conversion/orientation/TMEM bounds, canonical
headers, stable appended table IDs, ROM/runtime reporting, failure isolation,
undo/redo, project reopen, image-browser/material/OBJ interoperability and
untouched stock assets. Full headless regression and native RTX/OpenGL workflow
checks precede user gameplay review. Preserve unsaved editor windows; do not
generate persistent review ROMs or run an emulator. Stop after24 for review.
Course-building helpers followed as25. Autosave/recovery were subsequently
deferred again; course naming/text is proposed next.

Implemented in v1.19.0: MTL diffuse PNG/color/opacity loading, source/N64 previews,
RGBA16/32 dimensions/alpha/wrap choices and driving surfaces. Dedicated static
3D images append after stock IDs, with canonical32-byte headers,4 KiB TMEM and
ROM/table checks. Stock texture bytes remain unchanged. Geometry/artwork share
one undo step; version11 projects embed baselines and later pixel edits, while
versions1–10 retain earlier permissions. Image browser/material selectors and
OBJ/MTL/PNG export support the additions. See
[CUSTOM_TRACK_ARTWORK.md](CUSTOM_TRACK_ARTWORK.md).

Verification:1,261 full tests passed in312.25s; final affected checks cover the
additional MTL statement-order case and parser bounds. Native RTX4060 GL3.3
passed real file choosers, responsive worker/cancel, conversion/alpha/clamp,
TMEM refusal, material surfaces, atomic history, browser edits, v11 reopen,
OBJ/PNG and narrow inspector. The native run exposed and fixed NumPy sprite
equality during artwork cache refresh, with two regression checks. Original
Rev1 ROM SHA-1 is unchanged; no review ROM or emulator run was generated.
User gameplay review, 2026-10-20: the user confirmed that all new textures
appeared and completed the track without issues. This closes the representative
Phase24 gameplay gate. The user subsequently brought course-building helpers
forward as25; autosave/recovery briefly occupied26 and were deferred again.

### Phase 25 — Course-building helpers (implemented; gameplay review pending)

The user authorized this after24 gameplay review. Add an explicit staged course
builder for checkpoint placement/order/headings, paired-alternate renumbering,
racer start-grid layout and actionable course diagnostics. Reuse the existing
structural map/identity, project, terrain and export safeguards. Preview point
placement on the loaded geometry, generated lanes/grid, affected maps and exact
ROM budgets before one atomic Apply/undo. Preserve unrelated sets, entrances,
entries/unknown bytes, imported geometry/artwork and open unsaved editors.

Gate: source-verified yaw/forward/plane math, selected-set60-entry bound including
alternates, explicit alternate handling,8 indexed starts per entrance, terrain/
signed-coordinate checks, stale/refused plan isolation, multi-map stable IDs,
notes/history/project/ROM round trips and untouched assets. Full headless and
native RTX/Qt checks precede user gameplay review. No review ROM/emulator runs.
Stop after25 for review; autosave/recovery/backups are deferred. Any next
implementation requires the user's selection/authorization.

Implemented in v1.20.0 under Tools → Routes → Course builder: independent staged
road-click placement, editable point rows, midpoint/order/reversal, optional
tangent headings/lane reset, paired-alternate renumbering/removal and an8-racer
entrance grid. Preview includes lanes/start arrows, actionable diagnostics and
exact ROM/shared-level reporting. One Apply/undo reuses stable map identities
and project versions7–11. See [COURSE_BUILDING.md](COURSE_BUILDING.md).

Verification:1,299 full tests passed in237.24s; final shared-map report fix and
stock-restoration case pass82 affected tests in49.73s (38 course checks).
Native RTX4060 GL3.3 passed the real Routes button/modal, numeric editors,
top-view mouse movement/placement, grid layout, rejected plans, all views,
atomic two-map history, retained notes/custom geometry/artwork/scenery, v11 GUI
reopen, cancel and narrow inspector. Normal launch is clean, original ROM SHA-1
is unchanged. User gameplay review is next; no review ROM/emulator was generated.
Latest user review: the helpers seem to work; broader testing remains pending.
The user explicitly deferred autosave again and asked for the next suggestion.

### Phase25 refresh — Fresh-course workflow, v1.25.0

User-authorized follow-up to the Course Builder usability review. Clear all
placed objects or categories across both maps; keep geometry/artwork/settings.
Add live numbered point/grid placement, two-click grid direction, whole-grid
movement, nearby clicked-layer surface snapping, full-grid approach fitting,
draft undo/redo, direct Edit-menu access and actionable readiness feedback.
Fresh courses can copy the route to all existing mapped vehicle sets without
changing header references. Existing untouched routes are not renumbered by
cleanup/grid-only actions. Review/Apply retain one atomic structural transaction,
source bounds, project versions and all export protections. See
[COURSE_BUILDING.md](COURSE_BUILDING.md). Automated and isolated native gates
precede user gameplay review; no test ROMs or emulator runs. Autosave remains
deferred. Stop after this refresh for user review.

Gate passed:1,639 full tests (416.26 s),60 final focused checks (17.65 s),
including the final stored-plane regression, and isolated native mouse/RTX
checks on all three starter courses. All16 guide anchors per course snap,
including Gentle Hills. Whole-grid/checkpoint drag/history/cancel, cleanup byte
preservation, one atomic Apply/Undo and exact project/ROM checks pass. Normal
module smoke passes GL3.3/4x MSAA at63.8 FPS. Source ROM and user sessions remain
unchanged. User gameplay review is next; no further phase is authorized.

### Phase 26A — Course names (implemented; gameplay review pending)

The user authorized course names only, in their own window reached by their
own menu item. Latest steering puts Course Names and Texture Browser at the
bottom of Edit after a separator. Edit the existing level-name assets, retain
unmodified language strings/bytes, validate the game's character encoding and
display limits, update the editor catalog/search, and support undo, projects,
exact ROM preflight and export. Keep level IDs, menus/progression and save slots
unchanged. Existing decoding is in src/core/level_header.py; inspect the local
extractLevelName.cpp, DKR text encoder/font definitions and runtime consumers
before implementing a writer.

Gate: every stock name decodes/re-encodes without loss, invalid glyphs/lengths
are refused, language/terminator/table rebuilding is verified, unrelated assets
are retained, and project/history/export/native checks pass before user game
review of the displayed names. Preserve existing unsaved editor windows; no
persistent review ROMs or emulator runs. Stop after this scope for user review.

**Menu/dialogue text is excluded**, with no follow-on phase authorized. It may
be selected later as a separate scope with its own encoding/formatting research.

v1.21.0 implements a separate Edit → Course Names window, all65 rows, EN/DE/FR
drafts, retained JP bytes, font glyph/length validation, width warnings, exact
name/RAM/ROM reporting and atomic history. Version12 adds protected variable-
length name records; old writer permissions remain intact. Full1,409 tests pass
in227.42s, including109 course-name checks;246 focused integration checks pass.
Native RTX4060 GL3.3 checks pass real Edit-menu placement/separator, both window
actions, typing/glyph refusal, multi-course preview/Apply, shared history, labels/
search/HUD without camera/panel changes, retained notes/imported geometry/artwork/
objects, v12 GUI reopen, draft/original/reset behavior and narrow inspector.
Original ROM hash is unchanged; no review ROM/emulator run was generated. Stop
for user game-name display review. See [COURSE_NAMES.md](COURSE_NAMES.md).

### Phase 27 — Global object properties (implemented; gameplay review pending)

The user selected global object definitions after the Blender guide. Implement
shared ObjectHeader editing in a separate Edit-menu window, preserving the
compact inspector. Scope: source-traced scale/draw distance, lighting, existing
shadow/water-effect parameters and compatible existing model/sprite/texture
assignments. Keep behavior/type/counts, allocation flags, pointers, translation,
attachment/particle/light/misc data and unknown bytes protected. Behavior
conversion and asset/model/animation replacement are separate milestones.

Gate: source layouts/consumers and ranges verified; reference/schema checks;
known affected-level/alias/map/actor/attachment/skybox reporting; staged atomic
Apply/undo; v13 projects with legacy permissions retained; exact ROM budget and
unchanged unrelated assets; native numeric/artwork/cache/history/reopen/GL
checks, then user gameplay review. See [GLOBAL_OBJECT_PROPERTIES.md](GLOBAL_OBJECT_PROPERTIES.md).
No test ROMs/emulator runs; preserve existing unsaved windows. Do not begin
another milestone automatically. Dialogue/menu text and autosave remain deferred.

v1.22.0 completes automated/native verification: 1,459 full tests pass in253.12s,
including50 global-object checks;129 final artwork/image checks pass. Native
RTX4060 GL3.3 passes the real Edit action/modal, inline fields, typed artwork
selection, invalid-reference refusal, atomic two-header Apply, sprite/model
refresh, shared history, draft discard, v13 GUI reopen and retained camera/
object count. Normal module launch is clean with4x MSAA. Header storage/tables
and unrelated ROM assets are preserved; the original ROM hash is unchanged.
No review ROM or emulator run generated. Stop for user gameplay review.

### Phase 28 — Object models and animation editing (implemented; gameplay review pending)

v1.23.0 implements a separate Edit → Object Models & Animation window for
existing fixed-topology XYZ/baked RGBA/UV edits, keyframes/playback, OBJ position
replacement, clip JSON exchange and verified attachment/sphere/broad-phase
fields. Shared uses, staged atomic history, v14 projects and bounded ROM/inflate
checks are integrated. Counts, topology, materials, mapping/normal-sharing and
frame control headers remain protected. See [OBJECT_MODEL_EDITING.md](OBJECT_MODEL_EDITING.md).

Gate evidence:1,540 full tests pass in283.02s;81 final model tests in17.93s.
All390 models/470 clips round-trip. Native RTX4060 GL3.3 verifies numeric edits,
playback/endpoint, file exchange, refusal, Apply/cache/history/v14 reopen and
retained camera/objects. Blender4.4 verifies three model round-trips. Original
ROM and existing user windows are preserved; no review ROM/emulator run.

Review2026-10-21: model256 Signs extrusion changes36 vertices/22 triangles to42
vertices/22 triangles+6 quads (34 triangles after triangulation). This exceeds
the current position-only importer. The model has no clips or attachments/
collision spheres, but retains14 mapped groups. The user subsequently authorized
the static topology compiler as Phase29 below.

### Phase 29 — Static object topology rebuilding (implemented; gameplay review pending)

User authorized new faces/extrusions after the sign256 review. Add canonical
static arrays/batches/references, source-material/UV inference for the existing
OBJ and explicit batch_N/UV/color exchange for future edits. Preserve original
opaque bytes, texture assets, model IDs and clip ranges; clip-bearing topology
remains separate. Reuse staged model preview, atomic asset history, GPU refresh,
v15 project records and bounded ROM export.

Gate: all207 static stock templates, exact user sign/quad case, command fields,
references/lighting anchors, normals/collision allocation reports, protected
prefix/flags, malformed/refused/stale isolation, project/legacy/coexistence and
untouched ROM entries; native file/preview/Apply/history/v15 reopen/GL and real
Blender material/UV/color exchange. No persistent review ROM/emulator runs;
preserve all existing user editors and both OBJ files. Stop for gameplay review.
See [STATIC_OBJECT_IMPORT.md](STATIC_OBJECT_IMPORT.md).

v1.24.0 completes automated/native gates: all 207 static stock templates rebuild;
49 new tests and 180 focused checks pass, with 1,589 full tests in 285.06 s.
The exact user extrusion imports as 40 stored vertices/34 triangles/3 batches,
adding 1,000 B shared model memory and 128 B ROM. Native RTX 4060 GL 3.3 checks
pass real import/export dialogs, independent preview, atomic Apply, live GPU
topology through undo/redo and version 15 GUI reopen. Blender 4.4 verifies
batch materials, UVs and colors for models 0/256/260. Original ROM and both user
OBJ files remain unchanged. No persistent review ROM or emulator run generated.
Stop for user gameplay review; another milestone requires separate authorization.

Phase 29 review: v1.24.1 corrects implicit material inference for extrusion walls.
The sign's geometry reached the GPU, but its new walls inherited the transparent
front decal. New surfaces now prefer aligned source materials while existing
faces and explicit batch_N choices remain intact. Legacy original-row reimports
retain reference positions, and a preview Textures toggle exposes solid shape.
The current sign compiles to 52 vertices/34 triangles/4 batches, adding 1,144 B
shared model memory and 224 B ROM. See the static import guide for reimporting.
Verification passes: 1,593 full tests in 299.92 s, including 53 static rebuild
checks; 134 focused checks and native RTX GL import/toggle/Apply/GPU/history/
v15 reopen pass. Normal v1.24.1 launch is clean. The OBJ extrudes the separate
decal layer; both front layers must be edited for a flush white board. Original
inputs and older editors remain intact. Stop for user review.

### Post-audit corrections — v1.24.2

User-authorized maintenance fixes new checkpoint-set project reopening,
space-saving recovery from an old ROM-budget error, environment-mapped model
compatibility and missing skybox/attachment image uses. Project IO, dependency
traversal and native checks have separate modules; existing project versions and
binary protections remain intact. Enter in shared-object/course-name fields no
longer invokes draft-reset buttons. Eight new regressions and the full 1,601-test
suite pass. See [CODE_AUDIT_FIXES.md](CODE_AUDIT_FIXES.md) for verification and
scope. This is maintenance of completed features; stop for user review.

### Second-audit corrections — v1.24.3

User-authorized maintenance validates edited checkpoint-set references before
map transactions commit, preserving valid save/reopen and atomic history. Valid
cross-map transfers and all object types remain available. The Texture Browser
refreshes dependencies/history after object edits without losing PNG drafts;
Enter no longer starts PNG export. Eight additional regressions and native
controls/project/GL checks cover the fixes; final gates are in STATUS.md. No
new project format or feature phase. Stop for user review.

Gate passed: 1,609 full tests (321.09 s), 194 focused tests (96.99 s), targeted
native workflows and complete smoke on RTX4060 GL3.3/4x MSAA (63.3 FPS).
Original ROM/OBJ files and user sessions remain intact; no persistent test ROM.

### Third-audit corrections — v1.24.4

User-authorized maintenance binds geometry/UV/RGBA cell edits to their originating
track through level switches and orders blended artwork across scene categories
by camera depth. Nine new automated checks cover model ownership/history/projects
and posed range ordering/filtering; native checks reproduce actual level clicks
and compare composited pixels. Details and current gates are in
[CODE_AUDIT_FIXES.md](CODE_AUDIT_FIXES.md) and STATUS.md. ROM-backed model/animation
and OBJ editing remain supported; structured decomp model glTF/JSON loading is a
separate, unimplemented path. No new editing phase or project version.

Gate passed: 1,618 full tests (328.27 s), 163 focused tests (51.00 s), native
cell/history and framebuffer regressions, all65-level rendering and complete
RTX4060 GL3.3/4x MSAA smoke at63.8 FPS. Source ROM/OBJ files and existing user
sessions remain unchanged. Stop for user review.

### Deferred — Autosave, crash recovery and project backups

Deferred again at the user's request after Phase25; no fixed next-phase slot.
When selected later, add recoverable
project checkpoints and bounded backup retention without overwriting the original
ROM or silently replacing a manually saved project. Recovery must validate the
base ROM, project version and embedded asset bounds before opening. Keep normal
save/undo behavior and respect user-selected storage/retention settings.

Gate: interrupted-write/corrupt-file recovery, original/manual-save protection,
base-hash and version checks, retention bounds, explicit recovery UI and regression
coverage. This phase has not started and requires separate authorization.

## Independent milestones to select later

The v1.25.5 [compact track OBJ follow-up](OBJ_SCALE_PLAN.md) exports XYZ×0.01
and imports at default×100, with Blender import/export at1. Shared constants,
game-space offsets and explicit segment staging preserve placement. The guide
and future starter generator use this convention; existing user files remain
untouched. Existing-project compatibility was explicitly not required.
Gates pass:1,777 full tests, all55 export-coordinate checks, isolated Blender4.4
round trips, native controls/history and complete RTX4060 smoke at62.7FPS.

The v1.25.6 object-model follow-up extends the shared1:100 OBJ convention to
static material exports and animated position-only meshes. Both import paths
restore×100 before rounding/bounds/reference matching. Blender import/export
remain Scale1; numeric model fields and clip JSON retain native units. See
[object-model editing](OBJECT_MODEL_EDITING.md). This does not advance a new
feature phase or change animation/topology/reference limits.
Gates pass:1,797 full tests (376.05s),163 focused checks/all390 lossless mesh
round trips and207 static coverage, isolated Blender4.4 static/animated edits,
native import modes/history and RTX4060 GL3.3/4x MSAA smoke at62.9FPS.

Maintenance v1.25.1 corrects imported geometry rendering batches and transparently
normalizes earlier imported projects during export. See [render batch correction](RENDER_BATCH_FIX.md).
This does not advance a feature phase; gameplay confirmation is performed by the user.
Automated gates pass: 1,649 full tests, 378 focused checks, native import of all
three starter tracks and complete RTX editor smoke. Existing project exports
are corrected without redoing course setup; user confirms the affected turn.

User confirmed that correction in-game. The v1.25.2 follow-up adds MMB drag
panning to shared viewports and makes checkpoint arrows show travel rather than
the opposite plane normal. Checkpoint bytes and course calculations stay
unchanged. Gates pass: 1,684 full tests, 243 focused checks, native pan lifecycle
in main/course/model/track windows and complete RTX editor smoke.

Maintenance v1.25.3 keeps scenery sprite cards upright in Perspective so looking
down no longer tilts tree canopies into nearby walls. CPU picking follows the
same basis; depth occlusion and orthographic editing remain intact. This is an
editor preview convention, with no ROM/project format change. Gates pass:
1,698 full tests, 58 final focused checks after the translucent sorting
refinement, native doorway/picking/front-and-rear wall checks, and RTX editor
smoke. See [scenery preview correction](SPRITE_OCCLUSION_FIX.md).

The v1.25.4 About follow-up replaces the user's illustrated banner with
ROM-derived artwork while retaining their layout and interactions. This does
not advance the editing roadmap. See [About artwork](ABOUT_ARTWORK.md) for
asset references and headless/native verification.

These cover remaining audit opportunities and can be brought forward after
prerequisites. Give a selected item its own active phase/gate. Listing them does
not authorize implementation or require completing all of them in sequence.

| Milestone | Scope / prerequisite | Verification gate |
|---|---|---|
|Menu and dialogue text|Separate deferred scope; course names are Phase26A. Menu/textbox encoding/formatting needs research.|Languages/terminators, rebuilt indexes, retained unsupported bytes, export/reload and game text.|
|Racer balance|Verified MISC weight, handling, acceleration and hitbox assets after Phase 10.|Trace consumers, bounds, table/project round trips and controlled game comparisons; compiled physics stays separate.|
|Weapon mappings and AI|BALLOON_DATA and existing AI behavior/difficulty after Phase 10.|Valid references, source-traced fields, isolated export and pickup/AI game tests; unknown codes stay unknown.|
|Menus and progression lists|Existing track/hub/battle/boss lists, title demos, magic-code text after project/text writers.|List/reference checks and menu/game tests; new mechanics/levels/save expansion are separate.|
|Audio tools|Browser/preview first; bank/SFX/music replacement later. Existing music references are Phase 11.|Verified bank formats/references/alignment, bounded rebuilding and game playback; raw extraction is not import support.|
|Particles and special effects|Separate preview/edit gates for emitters/weather, lens flares, lighting/shadows and vehicle assemblies.|Source consumers/structs, conditional-state labels, preview/export and game effects. Split systems before implementation.|
|HUD and fonts|Element mappings, glyphs and art after texture/text writers.|References/glyphs/encoding, shared uses, export reload and game readability; compiled layout stays separate.|
|T.T. ghosts|Read/visualize first, then import/edit paths, times and metadata.|Verify timing/count limits, consistency, bounded serialization and game ghost playback.|
|Sharing and testing|Portable patches and optional emulator-launch profiles after Phase 10; autosave/recovery remain deferred.|Base hashes, reproducible patches, original protection; launching does not prove playtesting.|

Code patches for new mechanics, compiled physics/weapon rules, extra levels and
save/progression expansion stay outside asset editing until separately requested.
