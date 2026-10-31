# Code-audit corrections — v1.24.2–1.24.4

## Third-pass corrections — v1.24.4

Geometry XYZ cells and material UV/RGBA cells defer their edits until Qt has
finished committing the delegate. These requests now carry the originating model
ID. Clicking another level to commit a cell applies it to the original model,
keeps the newly selected level/camera in view and records the correct asset in
Undo/Redo and the saved project. Immediate geometry and material controls use
the same explicit model ownership. History can still reveal its affected track.

Opaque and cutout artwork writes depth first. The viewport then collects blended
track ranges, sprite tiles, individual posed model ranges, special artwork and
water into one camera-depth queue. This prevents list/category order from
placing a farther transparent object over a nearer one. Animated range centers
use the displayed pose and full instance transform; hidden actors, sprite frames,
segment isolation and water replacement retain their filters. Sorting uses view
depth rather than distance from the camera, including orthographic views.
Centers sort draw ranges, so intersecting transparent polygons may still need
geometric splitting for exact compositing. This changes preview rendering only.

Nine added automated regressions cover deferred XYZ/UV/RGBA ownership through
level switches, undo/redo and project reopening, background asset refresh,
off-axis depth, posed/scaled range centers, sprite frames/hiding, segment filters
and the shared category queue. Native checks repeat actual field-to-level clicks
and framebuffer comparisons with reordered objects, reversed cameras and
track/sprite/model overlap. Verification totals are recorded in STATUS.md.

Verification: all 1,618 tests pass in 328.27 seconds; 163 focused checks pass in
51.00 seconds. Native real cell/level clicks preserve the original target,
newly selected camera and history. Framebuffer comparisons are invariant under
object reordering and reverse correctly with the camera. All 65 levels render
sampled artwork/water/fog without GL errors, including orthographic views. The
complete native smoke suite passes at 63.8 FPS on RTX4060 GL3.3 / 4x MSAA.
The original ROM and both OBJ hashes are unchanged; user windows are preserved.
Temporary test outputs were cleaned; no persistent test ROM or emulator run.

"Extracted models" means the decomp extractor's structured ObjectModel glTF/JSON
output. Importing that representation is not implemented. ROM binary models and
clips, the Object Models & Animation window and its existing OBJ exchange remain
supported. This fix adds no extracted-model importer or new editing milestone.

The read-only audit found four cross-feature problems. This maintenance update
fixes them without changing binary formats or adding a feature phase.

## Project loading

Project IO lives in `src/core/project_io.py`; `EditSession` retains its public
save/load API and owns state/history. The loader builds a private session,
installs structural maps, then validates level settings against the complete
checkpoint data. A new Course Builder set can therefore be selected in level
settings and reopened. Missing sets, protected bytes, invalid hashes, malformed
maps and old-version writer permissions remain rejected. Project versions 1–15
and the existing version-selection rules are retained.

## Budget recovery

Previews replace old storage-layout errors with checks of the entire candidate
layout. They retain unrelated runtime and writer refusals. The shared logic in
`src/core/export_report.py` is used by course names, course plans, shared headers,
model editing and track-import previews. Restoring shorter names or importing a
smaller track can repair an over-budget session. Apply revalidates the candidate,
and undo/redo retains the prior export state. The original-ROM size/padding,
section alignment, compression and runtime checks are unchanged.

## Model compatibility

`ObjectModel.normal_vertex_count` follows the local
`object_models.c:model_init_normals`: a batch generates normals when
`miscData != BATCH_VTX_COL` **or** `RENDER_ENVMAP` is set. Compatibility checks
and static-rebuild RAM estimates now share that definition. Stock model 354 is
correctly classified as requiring normals, so swapping an unlit sign model to
it is refused by the existing lighting-layout protection.

## Artwork dependencies

`src/core/object_dependencies.py` supplies one graph for shared-object/model and
image reports. It follows placed objects, animation targets, attached headers
and level skyboxes. Flash-sky texture references are also included in image
reports. Header/name changes invalidate the image-use cache; open image browsers
refresh after settings, names and structural changes. For example, texture 1091
lists Central Area, and its label updates after renaming that course.

These remain known data-backed uses. Compiled gameplay/menu spawns can add uses.

## Native workflow maintenance

Native checks moved out of the application entry point into
`src/ui/smoke_checks.py`, loaded only for `python -m src.main --smoke-test`.
The entry point is approximately 115 lines instead of 1,020. The checks account
for actual camera input-loop time, isolate the reference grid from environment
overlays and wait for queued selection before opening property editors.

Native verification also exposed dialog default-button behavior: Enter in an
artwork/name field could activate Restore/Reset. Shared-object and course-name
windows now commit text without implicitly activating those buttons. Escape and
explicit button clicks retain their behavior. Runtime title/application versions
share `src.__version__`.

## Second-pass corrections — v1.24.3

The first checkpoint fix made valid projects load in dependency order. The
second audit exposed a later mutation: deleting/reassigning the final main
checkpoint of a newly assigned set left an edited header referring to no set.
Saving then succeeded but reopening correctly rejected that missing reference.

Map transactions now validate edited checkpoint-set references before installing
any member. Delete, typed/raw/bit parameter edits, group changes and history use
the same check. A refusal leaves maps, notes, history and identity counters
unchanged; budget reporting and project reopening remain usable. Select another
set in Level settings before removing the assigned custom set. Both maps are
checked together, so a valid grouped transfer between maps still works. Existing
stock-value preservation and availability of all object types are unchanged.
The local checkpoint fields remain 0x17 u8 alternate / 0x1A s8 set ID;
objects.c sorts main/alternate checkpoints within the selected set.

An open Texture Browser now refreshes affected levels and Undo/Redo controls
after object edits/history. This context refresh retains a staged PNG import.
Enter in its numeric fields commits the field without starting PNG export or
implicitly applying the value; the explicit Apply buttons retain their behavior.

Eight additional automated regressions cover atomic refusals, retained notes,
save/reopen, valid cross-map group transfer, reassignment/deletion and browser
context through history. Native checks exercise the real Delete and browser
Undo/Redo buttons, pending PNG retention, Enter, explicit timing Apply and project
reopening on RTX 4060 / GL3.3. Full-suite verification is recorded in STATUS.md.

The full 1,609-test suite passes in 321.09 seconds; 194 focused checks pass in
96.99 seconds. The complete native smoke suite also passes at 63.3 FPS with 4x
MSAA. Original ROM/OBJ hashes and existing user sessions are preserved. All
temporary test outputs are cleaned; no persistent test ROM or emulator run.

## Verification — v1.24.2

Eight new headless regressions cover v7/v15 checkpoint-set reopening and invalid
references, real over-budget recovery, unrelated refusal preservation, smaller
track recovery, environment-only normal allocation and sky/attachment cache uses.
The full 1,601-test suite passes in 306.97 seconds. Native RTX 4060 / OpenGL 3.3 checks verify
save/reopen, live dependency/name refresh, undo, model refusal and name-budget
Preview/Apply. The complete relocated smoke suite also passes camera/input,
track textures/geometry, picking, sprites, typed/raw/bit editing, mouse moves,
cancellation, shared history and project/ROM export at 63.4 FPS with 4x MSAA.
Temporary projects and test ROM files are automatically removed;
no emulator runs or persistent test ROMs are produced.

The user's existing editor/Blender sessions, original ROM and OBJ inputs remain
untouched. Stop for user review; no next feature milestone is implied.
