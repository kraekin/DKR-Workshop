# Project overlays and export preflight

Source references: local asset_loading.c:asset_table_load, buildObjectMap.cpp,
DKRCompression.cpp and tools/n64crc.c. All runtime application code stays in src/.

Projects retain `format: dkr-object-project`. Saves use version15 for static object
topology rebuilds, version14 for fixed-topology object-model/
animation edits, version13 for global
object definitions, version12 for course
names, version11 for dedicated
custom artwork, version10 for spatially
compiled imports, version9 for original single-segment imports, version8 for
geometry, version7 for structural maps, and version6 otherwise. Versions1–14 remain
readable with their former writer permissions. All identify the verified original Rev 1 ROM by SHA-1
and store existing object edits in `edits`, with original map/index/ID/entry hash
and changed byte offsets. Version 2 adds `asset_edits`: section/index, original
asset SHA-1 and changed bytes. Only writers enabled for the saved project version may load these edits. No arbitrary section or raw-ROM patch
support is implied. Fixed assets retain their original record length. Supported level-header edits cover only the verified fields in [LEVEL_SETTINGS.md](LEVEL_SETTINGS.md);
Supported material edits cover the existing LevelModel fields described in
[TRACK_MATERIALS.md](TRACK_MATERIALS.md). Version5 adds the verified fixed minimap
settings in [MINIMAP_SETTINGS.md](MINIMAP_SETTINGS.md). Version6 adds the image
and anchor writers in [IMAGE_ASSETS.md](IMAGE_ASSETS.md). Version7 adds stable
structural object rows in [OBJECT_EDITING.md](OBJECT_EDITING.md). Version8 adds
constrained vertex XYZ in [GEOMETRY_EDITING.md](GEOMETRY_EDITING.md).

Version9 adds `track_imports` for the canonical single-segment compiler in
[CUSTOM_TRACK_IMPORT.md](CUSTOM_TRACK_IMPORT.md). Each row has model `index`,
original decoded `base_asset_sha1`, and hex `baseline`/`current` byte strings.
The baseline is validated independently: canonical layout, counts, slot metadata,
generated bounds/facets/PVS, static batches, normal/cutscene runtime and inflater
limits. Current bytes pass the existing fixed-topology material/minimap/geometry
writers relative to that baseline, plus generated collision-plane checks.

Version11 adds `custom_textures`, an ordered array of canonical raw static RGBA
texture hex strings. IDs are the original3D texture count plus array position;
no stock ID is replaced. The pool is validated before model/asset overlays, with
128-assets/15-bit-ID bounds,32-byte protected headers, single frame, aligned stride,
power-of-two dimensions and4 KiB TMEM. Existing pixel/timing overlays can target
these baselines using their hashes; dimensions/format/flags remain protected.
The track and appended images share one import history record. Failed preview/
Apply restores the original pool. Undo removes that import's additions, redo
restores them, and stock geometry restore retains stable image IDs. Sections2/3
are rebuilt with appended offsets; ROM budgets include all images and table
alignment. Versions1–10 reject `custom_textures` and cannot opt into new IDs.
See [CUSTOM_TRACK_ARTWORK.md](CUSTOM_TRACK_ARTWORK.md).

Version12 adds `course_names`, an array of existing course `index`, original
`base_asset_sha1`, `encoding: raw-names` and bounded hex `data`. The full raw
record supports variable-length Latin names while retaining the exact Japanese
string and opaque tail. Names are validated against original hashes, glyphs,
63-byte limits and the protected language layout. Duplicate IDs, unsupported
sections/encoding, malformed data and legacy-version name records are rejected.
They cannot be installed through `asset_edits`. Sections24/25 rebuild together
with stable IDs, retained sentinel/tails and exact ROM alignment/budgets.
Version12 retains artwork/import/structural support; versions1–11 gain no name
writer permission. See [COURSE_NAMES.md](COURSE_NAMES.md).

Version13 enables fixed-length section34 global ObjectHeader overlays in
`asset_edits` with `encoding: raw`, base hashes and changed byte offsets.
Source-traced scalar fields and existing artwork IDs are writable; all other
bytes, counts, pointers and tail data stay protected. References pass model,
animation/attachment/lighting or sprite/texture frame compatibility checks.
Section33/35 tables and header lengths do not change. Definitions and cached
maps refresh after load/history. Versions1–12 cannot opt into this writer.
Version13 retains all earlier course-name/artwork/import/structural support.
See [GLOBAL_OBJECT_PROPERTIES.md](GLOBAL_OBJECT_PROPERTIES.md).

Version14 enables sections29/32 object-model/animation overlays in `asset_edits`
with `encoding: rare-decoded`, original decoded hashes and changed byte offsets.
Both retain decoded lengths, counts, topology, animated mapping, normal-sharing,
clip/frame counts, control headers and unknown bytes. Source-verified vertex/
baked color/UV, attachment-index, sphere and broad-phase fields are writable;
clip group offsets re-encode signed16 initial/signed8 incremental values. Tables
28/31 rebuild with stable IDs and retained tails. The model-to-clip table30 is
unchanged. Exact combined ROM and0x80-slack in-place inflate checks precede Apply
and export. Versions1–13 cannot opt into model/clip writes. Version14 retains all
earlier project features. See [OBJECT_MODEL_EDITING.md](OBJECT_MODEL_EDITING.md).

Version15 adds `object_rebuilds`: existing model `index`, original decoded
`base_asset_sha1`, `encoding: static-model` and bounded hex `data`. Each has a
protected original prefix plus canonical appended arrays. Static eligibility,
source batch/material/triangle flags, clip-table preservation, references,
signed fields, layout/padding and editor resource bounds validate before load.
Mixed byte overlays/rebuild records for the same model, duplicate records,
tampered opaque data and all such records in versions1–14 are rejected.
Source-sized decode+0x80 in-place checks and exact ROM layout precede Apply/export.
Section28/29 IDs and unmodified entries/tails remain stable. Existing asset-group
history stores complete before/after bytes so undo/redo needs no hidden baseline
permission state. Restoring the last rebuild permits saving at an earlier version.
Version15 retains every earlier course-name/header/structure/track/artwork feature.
See [STATIC_OBJECT_IMPORT.md](STATIC_OBJECT_IMPORT.md).

Each imported track binary is bounded by the0x82A00 track heap. Duplicate model rows or mixed
legacy/import rows for the same model are rejected. Versions1–8 reject import
rows. Legacy overlays keep their existing permissions and cannot change topology.

Import/stock restore have typed history entries containing both model bytes and
baseline identity. Undo restores prior edits and permissions exactly. Subsequent
material, minimap and geometry operations retain their own undo steps. Import
baselines contribute to dirty state even when current bytes happen to match a
prior model. Projects embed the compiled geometry, so reopening needs the original
ROM but not the OBJ file. Original model lengths may change only through this
validated import path. Export recompresses changed entries and rebuilds table26;
other entries/sections retain their payloads. No generic raw model import exists.

Version10 retains the `track_imports` row shape. It adds the independently
validated spatial compiler in [SEGMENTED_TRACK_IMPORT.md](SEGMENTED_TRACK_IMPORT.md):
uniform cells, at most120 rendered/collidable faces per cell, generated BSP and
all-visible PVS, protected hidden/no-collision seam guides, bounded runtime and
source inflater lookahead padding. Additional TextureInfo slots may separate
surfaces sharing an image; original slots remain present. The decoder accepts
legacy v9 baselines alongside v10 ones. Version9 explicitly calls its former
single-segment validator and cannot gain the new permissions by supplying a
segmented buffer. Saves choose the highest baseline version needed; history
restores baseline bytes and therefore the corresponding permissions exactly.

Current overlays retain topology, cell bounds, BSP/PVS and serialized facet links.
Seam-guide flags and non-water surface semantics remain protected. Guide XYZ
groups are locked until reimport; interior XYZ, material and minimap edits retain
their verified writers. Normal ROM export uses the same padded compression as
preflight. OBJ export omits generated guide faces so they cannot become visible
duplicates or be reimported as ordinary geometry. Guides remain in project/ROM
data because runtime edge-plane generation uses their neighboring normals.

Version4 model overlays use section27 and `encoding: rare-decoded`; the base hash
and offsets refer to the complete original inflated model entry. Header overlays
use `encoding: raw` (absent in older projects). Decoded lengths and all protected
collision/count/offset bytes must match the base. XYZ stays protected in versions
1–7; v8 requires linked coordinates and the verified spatial envelope. The writer compresses
changed entries and rebuilds subtable26 plus master offsets. Models are not
treated as fixed compressed spans. Header/map/model edits share history, projects,
growth reports and atomic original-ROM-safe export. Old projects cannot opt into
model overlays by adding a section27 entry; they require version4 or later and
its encoding. Version4 model overlays still pass the original material-only
whitelist; version5 and later admit minimap field bytes. The combined validator
retains collision/count/metadata protection and each writer's field constraints.
Geometry, minimap and material reverts each preserve the other writers' changes.

Version6 texture overlays (sections2/4) use `encoding: texture-decoded` and hash
the canonical container: outer32 + full inflated entry if compressed, otherwise
the complete raw entry. Pixel spans and verified timing are writable; layout,
dimensions/formats/counts/flags/palettes/padding remain protected. Sprite section12
raw overlays allow only signed16 anchors at4/6. Multi-tile sprite PNGs become
per-texture overlays with one grouped asset history operation. Tables3/5/13 are
rebuilt on export. Versions1–5 cannot load image overlays.

Version 3 adds `research: {experiment, notes}`. Each note contains its original
map ID/entry index/base-entry SHA-1, source field key (or `position:X`/`byte:24`),
text and an observation result. Notes are validated against the original schema;
duplicates, missing fields, wrong hashes and malformed values are rejected.
The source-backed field classification is not overwritten by an observation.
Research metadata contributes to project dirty/save/undo state, never to ROM
bytes or compressed-asset capacity. A notes-only project exports the exact base
ROM in memory. Structural notes retain base/creation identities in v7–v11.
Saving migrates to v6/v7/v8/v9/v10/v11 according to current edits; older builds may reject
newer versions.

History contains typed object-map, group, asset or research changes in a single undo sequence.
Loading a project establishes its saved state without inventing undo records.
New operations clear redo; no-op edits do not. Unknown bytes remain intact.
Group gestures snapshot affected maps and commit once; cancellation restores
all original members. Projects continue to store final per-entry byte overlays,
so grouped editing does not require insertion, identity aliases or renumbering.

The Research UI was retired in v1.15.1. Existing experiment names and notes
remain compatible and are retained on save. The core read-only comparison API
still compares typed properties, raw bytes, header/model edits and metadata
against the same verified base ROM without importing values.

The export report and ROM writer use the same prepared section layout. Changed
object maps are compressed using LE u32 length + 09 + raw DEFLATE, aligned 16;
unchanged entries, section tails and table terminators retain their bytes.
Master offsets are relative to LUT_END 0xED1B0. Sections retain 16-byte alignment.
Report details include decoded/stored lengths, growth, relocations, byte/property
diffs and all levels referencing the edited map. Shared uses come from original
LevelHeaders; future reference-changing writers must update this analysis.

Original Rev 1 size 0xC00000, final asset end 0xB8CFD0, usable trailing padding 471,088
bytes. Preflight reports negative remaining space and blocks export if the
layout exceeds padding, would overwrite non-padding bytes, or loses section
alignment/count. It does not add game RAM or validate every gameplay reference.
No-edit export is byte-identical. Edited export updates N64 checksums and verifies
every written section before atomically publishing a new file.

UI: File → ROM Budget and Project Changes; Copy report copies the readable text.
The status bar gives rounded KiB; the report/tooltip gives exact byte counts.
Opening/copying a report does not edit the project (an active editor cell/drag is
committed first, as with save/history).

Before structural object editing, projects used version6. Structural changes were
rejected by its existing-entry writer and could not be installed through additional
`structural_maps`, `structural_edits` or `stable_entries` keys. The separate,
headless `dkr-structural-research` version1 draft prototypes stable original/new
identities, template provenance and history. Import uses the normal v1–6 loader
first; a matching source signature/map digest is required to reopen a draft.
It is not a normal `.dkrproj` and adds no production operation/UI permissions.
See [STRUCTURAL_SAFEGUARDS.md](STRUCTURAL_SAFEGUARDS.md) for its limitations and
its separation from ordinary project object editing.

Course Builder plans reuse the existing structural map state and stable IDs.
One Apply can update both loaded maps, preserving retained field notes and
unrelated entries. New course-only projects use version7; imported geometry or
custom artwork keeps the needed higher version. No additional project version
or legacy writer permission is introduced. Preview drafts are not installed in
the session or saved until Apply. See [COURSE_BUILDING.md](COURSE_BUILDING.md).

Since v1.24.2, `src/core/project_io.py` owns the schema and loads structural maps
before validating level-header checkpoint references. Existing projects that
create and select a new checkpoint set can reopen without manual conversion.
All hash, protected-byte, reference and version checks remain in force. See
[CODE_AUDIT_FIXES.md](CODE_AUDIT_FIXES.md) for the related budget/dependency fixes.

Since v1.24.3, candidate map edits preserve the validity of edited header set
references before committing. To delete/reassign the last main checkpoint in an
assigned custom set, select another existing set in Level settings first. Grouped
changes validate both loaded maps together. This closes the edit-time path to an
unreopenable project without changing versions or weakening loader validation.
