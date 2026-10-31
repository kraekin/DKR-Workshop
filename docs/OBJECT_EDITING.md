# Object creation, duplication and deletion

The Objects tab now has **Add…**, **Duplicate** and **Delete** buttons. Every
one of the ROM's304 valid translated object IDs is available, including racers,
collectables, scenery, checkpoints, AI nodes, cinematics and runtime/unknown
objects. Templates prefer original placed entries where available; types without
stock placements use source-schema defaults. Review copied links and node IDs
when adding or duplicating objects.

## Using the tools

- **Add…** opens the searchable full catalog. Choose an object, one of the
  current level's two object maps, and signed16 X/Y/Z coordinates. The dialog
  lists other header-referenced levels affected by that map.
- **Preferred template** copies actual stock entry parameters where a matching
  header has an existing placement.85 header types have stock templates. For
  the other219, it explicitly initializes a zeroed record using the verified
  source schema. **Zeroed schema defaults** is also selectable for placed types.
  Template source and byte size are shown. Zero values are initialization
  choices, not claims about correct gameplay defaults.
- **Duplicate** / **Ctrl+D** copies the selected entries' current parameters
  and raw unknown bytes, and offsets X by the movement Step. It supports
  multiple selected objects across both loaded maps as one undo step.
- **Delete** / **Ctrl+Delete** removes the selected records as one undo step.
  Ctrl+Z restores them with their identities, parameters and research notes.
- Move and edit the added objects using the same mouse handles, spinboxes,
  property delegate, raw-byte/bit editor and placement tools as existing objects.

The buttons use the existing inspector; there is no additional toolbar row.
Object-list search/category filters remain in place through edits and history.
New/deleted selections and artwork refresh without reframing or slowing the
camera. **Map / editor ID** is a persistent editor identity, while
**Serialized entry** shows the current ordinal written to the ROM stream.

## IDs, links and gameplay testing

All types can be added, duplicated and deleted. These operations do not silently
renumber checkpoint indices, allocate new AI graph IDs, rewire adjacency links,
change cinematic actor/channel relationships, repair progression IDs or cascade
deletions. Those bytes are copied as-is and remain editable. The feedback panel
reports known links and graph implications without blocking the type.

For a new checkpoint/AI/cinematic node, inspect its index/ID/channel/order and
link fields before testing. The existing route/cinematic tools help edit those
fields. Duplicate identity values may require changes elsewhere; a source schema
and valid serialization do not imply that the game will accept the behavior.
Some runtime-only objects normally receive extra setup from game code and may
not work as persistent placements. The editor exposes them for investigation.

Save a project and export a new ROM through the existing File menu. The verified
base ROM stays the source; do not reopen the edited ROM as a new editor base.
For game tests, boot the exported ROM fresh. An old emulator state can contain
the old maps and objects. The user owns gameplay verification; no emulator was
launched and no persistent review ROM was generated during implementation.

## Stable history and project version7

Original editor IDs retain their original entry indices. New objects receive
monotonic per-map integer IDs that are independent of serialized order and
are not reused after undo/branching in the session. Deleting an earlier entry
does not move a surviving object's properties or notes onto another object.
An original object's Revert restores its original bytes; a newly created
object's Revert restores the snapshot taken when it was added or duplicated.

Structural edits use version7 `.dkrproj` rows: ordered stable IDs, original-map
hash, template provenance/hash, creation-snapshot patches, current patches and
the next identity counter. Reserved map-header bytes and surviving raw entry
bytes are preserved. This is separate from the old isolated research-draft
format, which is still refused as a normal project.

Versions1–6 remain readable. Projects with no current structural changes retain
the existing version6 format. A version7 project still resolves all template
bytes from the supplied verified original ROM; it does not require a different
ROM or an alias package. Duplicate/missing IDs, tampered provenance/hashes,
prefix/size changes, duplicate maps, invalid patches and mixed legacy/structural
edits for the same map are refused.

Undo/redo includes additions/deletions and their notes/selection. Multi-map
operations validate the complete transaction before publication. Failed edits
leave entry data, history and identity counters unchanged. The project comparison
and export reports match by stable identity and describe added/deleted records,
rather than comparing shifted row numbers.

## Retained bounds and practical limits

The all-type scope removes type allowlists; it retains known binary boundaries:
9-bit translated object ID, six-bit entry length, signed16 coordinates, preserved
ID/size flags,16-byte map header/8-byte alignment,0x3000 map workspace and the
per-stream source-model in-place inflater. Combined header-referenced map roles
also check512 placed entries,255 references per header, the minimum object/header
pool demand and descriptor bound. Export recomputes tables/CRCs and keeps the
original ROM length and untouched-asset protections. Original ROM overwrite is
refused. File → ROM Budget and Project Changes reports storage and current uses.

These necessary checks do not establish a universal safe placed-object count.
Runtime effects/attachments/racers/weapons, behavior-specific block sizes,
reference lifetimes, caches, interaction/shadow buffers and fragmentation can
use more than a minimum estimate. The interaction routine has257 pointers;
each shadow buffer has400 records/800 triangles/2000 vertices. Arbitrary
addition peaks and full graph/progression behavior remain user tests. Raw
default records for unplaced types are explicitly untested.

## Evidence and verification

The user-confirmed one-bush experiment's ROM SHA256 is
`b254874044f63f2a767c0ac39a2ba9bcb2f04bb761552e96fefb8f79d0d2530c`.
Three new captures match its complete map5 bytes and contain all three bushes
at their expected coordinates with208-byte blocks. Header43/sprite108 refs are3,
and the largest free block is31,424 bytes, exactly208 below the earlier baseline.
Their list counts are175,196,203 and object-pool free bytes37,248/33,168/34,960.
The screenshot shows the nearby original and added bush. This validates that
experiment; broader type availability follows the user's explicit request.

Headless tests exercise all304 catalog IDs, add/edit/delete/undo, stock/default
records, graph diagnostics, stable identities/notes, version7 reopen/tampering,
multi-map history, bounds/refusal atomicity, comparison and in-memory export
reload/CRCs/untouched data. Native Qt/RTX tests exercise the real palette/search/
map/XYZ controls, buttons, selection/filter/history, graph operations, project
reopen, artwork, camera preservation and the unchanged four toolbar rows.
Full suite:875 passed in133.79s. Final32 affected graph/report/runtime tests
passed in1.75s after the final report/diagnostic changes. Compileall is clean.
Native checks additionally passed Ctrl+D and the actual failed base-ROM export
action, retaining source bytes/project state. Screenshots were inspected under
ignored artifacts (`phase21-object-palette.png`, `phase21-editor.png`). A normal
`python -m src.main` v1.14.0 launch is open on the RTX4060, GL3.3/depth24/4x widget
MSAA, for review. Existing editor/emulator processes were preserved.

### v1.14.1 preview correction

Adding or duplicating a RubberTree in Ancient Lake exposed an animation cache
bug. Its two maps are flattened into one viewport list. An insertion in map73
shifts the animation-camera entries from map5, but the cached timelines retained
their old viewport indices because their stable editor IDs had not changed.
The old camera owner then matched an existing BeachTree, which was drawn at
the camera path's position. No additional BeachTree was serialized.

The cache now includes each animation node's current viewport index. Add,
duplicate, delete and history changes refresh these mappings; unrelated object
movement still reuses the timelines. Existing projects require no migration.
Save the current project and restart the editor to load the corrected code.

Verification: both RubberTree and WeaponBalloon regression cases fail before
the fix and pass after it. Full suite:878 passed in129.46s. Native RTX4060
GL3.3 checks pass Add/Duplicate/Add/move/delete/history with correct timeline
owners and GPU sprite positions. A v7 project reload and in-memory export
retain the original map5 bytes and exactly three RubberTree additions in map73.
No emulator or persistent test ROM was created; existing windows were preserved.

### User gameplay review — 2026-10-20

The user confirms v1.14.1 resolves the preview issue and reports adding four
trees in Central Area, seeing them in-game and observing no other issues there.
Their Lua capture `dkr-rdram-20261020-132356-1.bin` matches all three Rev1 code
fingerprints. Its loaded map0 retains all209 stock entries unchanged; map68
retains all88 stock entries unchanged followed by exactly four RubberTrees
(object ID78/header48), for92 entries. Snapshot list use is265/512, with22,224 B
free in the object pool and a15,824 B largest free block. These measurements
describe that captured state; they do not establish a general object allowance.

Capture SHA256:
`93b70e2c4e54f3ebc930afc3c44439286d78eefc004d049b678ccb1f03c8c252`.
Read-only review left the capture unchanged and generated text/JSON evidence
under ignored artifacts. The capture verifies those additions in that scene; it does not establish
a general object or memory allowance.
