# Confirmed audit fixes — 2026-10-23

Implemented after checking each external audit claim against the current source
and local Rev1 decomp. The running application retains the user's DKR Workshop
name and 0.x version series; this patch is 0.25.7.

## Target and reference safety

- Cell edits and deferred inspector selection use a small owner-bound queue.
  Level changes, pointer selection, save and history flush those callbacks without
  calling the general Qt event loop. A background level-setting refresh never
  selects its originating level. Import captures and verifies its geometry target
  before committing edits and labels the geometry and affected courses explicitly.
- Explicit checkpoint-set changes and header restoration compare the requested
  sets with the live header and current main checkpoints. Restoring a deleted
  stock set is refused without modifying history. Original unsupported values in
  unrelated fields and deliberate fresh-course transactions retain their existing
  preservation rules. Cached catalog headers now follow edits and undo/redo.

## UI state

- Model summary rows replace the previous block, including selected-segment rows.
- Unrelated image-browser refreshes retain a staged PNG when its selected source
  asset is unchanged. A direct source-artwork change clears an obsolete preview
  with an explanatory message. Existing undo behavior continues to refresh artwork.
- Minimap refreshes merge pending controls onto current settings, including
  incomplete numeric text. Cinematic values are retained by stable node/field
  identity through same-node selection and track refresh; they clear on source
  replacement or removal of their node.
- Course Builder handles appear only for movable course/grid roles, including
  list-driven selection. Camera basis vectors respect cinematic roll.
- The retired research panel retains project notes without rebuilding its hidden
  widgets or overwriting the saved experiment name.

## Resources and legacy batches

- Restore stock track reclaims the unreferenced suffix of the dedicated texture
  pool. Current assets and all remaining imported baselines retain their IDs.
  Internal holes are retained until their higher IDs become unused; no references
  are renumbered. Undo restores the pool and any removed artwork overlays, and
  project schema versions remain unchanged.
- Local model_init_normals assigns a separate accumulator to each miscData=0xFE
  vertex row. Legacy rebatching now verifies the split accumulators. Flat/safe
  splits remain supported; a split that changes averaged normals is refused with
  instructions to re-import using current 24-vertex batches. Source bytes remain
  intact. Existing export-only normalization is retained.
- Object rendering reuses a bounded cache of expanded pose/color buffers for
  interleaved animation poses. Shared dependency reports and original animation
  owner models are cached; actor-target/structural/reference changes invalidate
  dependency caches, while XYZ edits retain them.

## Deliberately unchanged

Game fog constants and the fog-free translucent-water path, binding-point-zero
uniform blocks, independent artwork/gizmo filtering, untextured display policy,
valid project installation order, stock model/clip guards, and existing checkpoint
diagnostics were not established bugs and were not changed.

## Verification

Tests cover native Qt callback boundaries and stable import selection, draft and
summary refreshes, missing checkpoint-set refusal, cache invalidation, texture
pool/project/history round trips, shared baseline references, flat/curved legacy
normal splits and rolled cameras. Native OpenGL checks use owned windows and
in-memory ROM output; original and user-edited ROM hashes remain unchanged.
All 1,798 tests passed in 333.81s; 77 application sources parse. Five native
import/GL scenarios and the extended artwork/animation checks pass. Final results
are recorded in STATUS.md. No emulator playtests or
user-facing test ROMs are generated.
