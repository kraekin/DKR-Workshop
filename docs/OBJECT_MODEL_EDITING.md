# Object models and animation

Open **Edit → Object Models & Animation…**. This separate window starts at the
selected rendered object's model, including an Animation controller's actor.
The list contains all390 models; names come from the shared headers using them.
Sprite artwork stays in the [Texture & Sprite Browser](IMAGE_ASSETS.md).

Static models support extruded/added/deleted faces.
Leave OBJ import on Automatic or choose Rebuild static topology. See
[Static object importing](STATIC_OBJECT_IMPORT.md), including the supplied sign.

Edits change a **shared asset**. Every object using that model or clip receives
the change. **Known uses / limits** lists headers and levels, including actor
targets, attachments and skyboxes. Compiled racer/menu spawns may add other uses.

## Mesh editing

1. Select a model by ID, or filter by an object name.
2. In **Model vertices**, double-click X/Y/Z. Coordinates use game units, **Y up**.
   Animated duplicates and vertices sharing a smoothing position move together.
   Baked RGBA is editable; dynamic-lighting/environment normal bytes are protected.
3. **Face UVs** edits six signed s10.5 components per triangle:32 is one texel.
   Material assignments and texture slots stay fixed. Use the Texture Browser
   to replace the texture's pixels.
4. Inspect the separate viewport: RMB look, MMB drag pan, WASD fly, Q/E vertical, Alt+RMB orbit,
   wheel zoom and **Fit (F)**. Wireframe helps inspect shape changes.
   Turn **Textures** off to compare solid geometry with Blender.
5. **Preview pending changes** validates all drafts and reports known affected
   uses and exact ROM storage. **Apply pending assets** commits every pending
   model/clip together as one project undo step.

Apply refreshes the course viewport and retains its camera and placed objects.
Drafts never change the project until Apply. Closing discards unapplied drafts.
**Reset this model's drafts** drops its mesh/clip drafts. **Restore original
model + clips (draft)** stages restoration for Preview/Apply. Other models'
drafts remain intact. Undo/Redo use shared project history and are available
when there are no pending drafts.

## Blender / OBJ replacement

**v1.25.6 compact units:** both static and animated mesh OBJ exports write
coordinates at **×0.01**. Both import paths automatically restore **×100** before
integer rounding, bounds checks and reference matching. Leave Blender import
and export **Scale at 1**. A 0.01 Blender-unit movement becomes one model unit.
Model-space origin and the placed object's scale are preserved. Numeric mesh
tables, attachment/collision fields and clip JSON keep their original units.
Export a fresh OBJ; older raw-coordinate files are not automatically detected.

Verified with1,797 full tests, all390 lossless mesh round trips, static template
coverage, Blender4.4 Scale1/1 edits on animated240/static256/260, native import
modes/Apply/Undo/Redo and RTX graphics smoke. See STATUS.md for current results.

**Export OBJ + artwork…** writes the draft's base mesh, a companion MTL and
referenced PNG textures. Static and animated exports carry colors, UVs and named
`batch_N` materials. Keep the three parts together for textured Blender import.
Playback does not change the exported base pose; clips use their separate JSON
exchange. See [Object artwork export](OBJECT_ARTWORK_EXPORT.md).
**Import mesh OBJ…** uses
the selected mode: Automatic reshapes first, then rebuilds static topology when
needed. The following restrictions apply to **Reshape positions only** and
models with animation clips:

- Import the exported file into Blender with **Forward −Z / Up Y**, scale1,
  Clamp Bounding Box0 and **Validate Meshes off**. Keep Split by Object/Group
  off for this single mesh. Axes match the [track guide](BLENDER_TRACK_GUIDE.md).
- Reshape existing vertices. Preserve vertex order, connectivity, duplicates and loose
  vertices used by attachments or collision spheres. Do not merge, subdivide,
  remesh, decimate, add/delete topology or use modifiers that reorder it.
- Export only this mesh with the same axes and scale1. Disable modifiers, extra
  triangulation and normals. Materials/UVs may remain for visual exchange; the
  fixed-topology importer applies positions only.
  Blender4.4 has no separate Keep Vertex Order checkbox in its current exporter.
  The editor checks the actual returned vertex/face layout.
- Reimport into the model window. XYZ is multiplied by100, then rounds to signed16 integers. Counts,
  face connectivity/winding, animation-group consistency and normal sharing must
  match. Face sorting and cyclic corner rotations are accepted, because the
  original binary faces/materials stay in place. Blender may omit degenerate
  anchor faces; the writer retains those original records. A mismatch is refused
  without changing the draft or project. Numeric XYZ editing remains available
  if a file does not preserve vertex indexing. These options were checked with
  installed Blender4.4 using three stock models, including animated Dinosaur2.

Blender can omit unused loose vertices even with mesh validation disabled. If a
required attachment/collision row is missing, import is refused to protect the
reference; the scale conversion does not bypass that check.

Reshaping retains existing topology. The separate static compiler
supports different counts/batches with verified reference and resource checks;
animated topology/skeleton retargeting remains separate. The track importer
builds a different format.

## Animation editing

Choose a **Clip** beside the viewport. Static models offer only Base mesh.
The slider scrubs in sixteenths of a keyframe. **Play** advances one sixteenth
per60Hz tick; game behaviors may use other animation speeds. Clicking a table
pauses playback.

**Animation offsets** shows each animated group at the slider's current whole
keyframe. Double-click XYZ offsets to edit them. Values are signed integers
relative to the group's base vertex; linked duplicates share the deformation.
Changing the base mesh moves the animation reference shape while keeping the
clip's stored offsets.

The last stored frame is an **interpolation endpoint**. Scrub fully right to
inspect/edit it. Ordinary playback interpolates toward it during the preceding
interval rather than playing it as another complete interval.

DKR stores signed16 offsets initially, then signed8 increments. Each consecutive
XYZ change must fit **−128..127**. Invalid edits identify the frame/group; use
smaller movements across existing keyframes. The writer re-encodes both incoming
and outgoing deltas while preserving other keyframes' offsets.

**Export clip JSON…** writes this exchange format:

```json
{
  "format": "dkr-vertex-animation",
  "version": 1,
  "groups": 1,
  "frames": 3,
  "mapping_sha1": "hash provided by the exporter",
  "offsets": [[[0, 0, 0]], [[0, 10, 0]], [[0, 0, 0]]]
}
```

This illustration has one group and three stored frames. Actual exports contain
every group/frame. Keep the exported metadata, dimensions and ordering.
**Import clip JSON…** stages a replacement with matching mapping, group/frame
counts and valid delta ranges. Destination root/head controls and unknown
12-byte frame headers stay unchanged. This is vertex animation, not a Blender
skeleton/action importer.

The preview shows deformation under neutral lighting. It does not execute game
scripts, root motion, vehicle assemblies or collision responses. Its playback
rate does not replace the behavior's animation-speed logic.

## Attachments and collision

**Attachments** edits existing slots' vertex indices. Positions follow that
vertex's animation. Slot counts and the shared header's part assignments remain
fixed.

**Collision spheres** edits each existing sphere's center vertex and radius scale:

`world radius = (radius scale / 64) × placed object scale × 50`

The center follows the current referenced vertex. Only behaviors using this
collision path are affected; these are separate from other hitboxes and track
driving-surface collision.

**Collision settings → Broad-phase distance** changes early collision-distance
rejection. It is separate from each sphere radius. The sphere path tests against
this value+50; another model collision path scales it by the object's scale.
Review it when enlarging a model. The preview does not simulate these tests.

## Preservation, budgets and projects

For fixed-topology mesh/clip edits, decoded sizes, texture/material slots, vertex/face/batch counts, topology,
normal-sharing partition, animated mappings, clip ranges/frame counts, frame
headers, pointers, unknown bytes and alignment remain fixed. New triangle
collapses and invalid attachment/sphere indices are rejected. These constraints
retain allocation layouts; scripts/contact still require gameplay review.

Edited entries are recompressed and their subtables rebuilt with stable IDs.
Unmodified entries, table tails and unrelated sections retain their bytes.
Preview checks combined ROM storage and the game inflater's input staging,
lookahead and Huffman workspace with0x80 loading slack. ROM space is separate
from game RAM.

Fixed-topology model/clip edits use **version14** and hashed `rare-decoded` byte
overlays. All earlier course-name/global-header/structural/custom-track/artwork
features coexist. Versions1–13 retain their earlier writer permissions. See
[PROJECT_FORMAT.md](PROJECT_FORMAT.md).

Static rebuilds use version15, canonical appended arrays and separate model/
normal/instance/collision memory diagnostics. See [STATIC_OBJECT_IMPORT.md](STATIC_OBJECT_IMPORT.md).

Save the project, then explicitly export a new ROM for your gameplay test.
The original ROM remains read-only. No review ROM/emulator run is generated
automatically.

## Local source evidence

- `tools/dkr_assets_tool_src/fileTypes/objectModel.hpp`: serialized header0x58;
  attachment s16 vertex indices and collision `(s16 vertex, s16 scale)` pairs.
- `include/structs.h:ObjectModel`: runtime header0x80; attachment offset/count
  0x14/0x18, collision offset/word-count0x1C/0x20, vertex/face/batch counts
  0x24/0x26/0x28, broad-phase float0x3C, animated count/mapping0x4A/0x4C.
- `src/object_models.c`: pointer fixups, normal/collision generation, instance
  allocations, model-to-clip ranges and decoded-size+0x80 loading.
- `src/hasm/obj_animate.s`: s16 mapping/first offsets, signed8 increments,
  sixteenth interpolation and separately handled root/head control headers.
- `src/objects.c` near4994/5254: broad-phase/radius consumers; near3549/3607:
  current attachment vertex positions.
- Rev1 section28 model table0x55B0A0 (1,568B),29 models0x55B6C0 (851,872B),
  30 s16 clip ranges0x62B660 (784B),31 clip table0x62B970 (1,888B),
  32 clips0x62C0D0 (654,192B).

Evidence comes from the local matching decomp. Application data does not embed
extracted proprietary models or clips.

Verification:1,540 full tests pass (283.02s), plus81 final model checks (17.93s).
All390 meshes/470 clips round-trip; source delta/wrap/interpolation, protected
bytes/structures, atomic history, v14 coexistence/legacy refusal and in-memory
ROM isolation pass. Native RTX4060 GL3.3 verifies the real window, numeric edits,
endpoint playback, file exchange, cache refresh, history and project reopen.
Blender4.4 round-trips models0,240,260. Gameplay review remains user-run.
