# Static object rebuilding

Open **Edit → Object Models & Animation…** and select the model being replaced.
Static models can now gain or lose vertices/faces, including Blender extrusions.
Animated models still use the [fixed-topology workflow](OBJECT_MODEL_EDITING.md).
This replaces an existing model ID; it does not add IDs or animation slots.

**Current exchange, v1.25.6:** export a fresh mesh OBJ at1/100 size. Leave
Blender import/export **Scale1**; the model importer restores×100 automatically
before rounding, material/reference matching and bounds generation. Numeric
model fields and animation JSON remain in native units. No unit guessing or
conversion of existing files/projects is performed.

## Importing an edited sign

1. Select **model 256 — Signs** in the list.
2. Leave **OBJ import → Automatic (reshape / static rebuild)** selected.
3. Export a fresh mesh OBJ, edit it in Blender with Scale1 in both directions,
   then click **Import mesh OBJ…** and choose your newly exported file.
4. Review the independent preview, including its new faces and their appearance.
   Use **Alt + RMB** to orbit; turn **Textures** off to inspect the solid shape.
5. Click **Preview pending changes**, review affected uses and the ROM/RAM report,
   then **Apply pending assets**.
6. Save the project and explicitly export a new ROM for your game test.

Historical raw-unit reproduction: `D:\RomHacking\n64\model_256edit.obj` had six
convex quads that triangulated automatically in the earlier raw-unit importer.
That existing file is unchanged; use a fresh compact export for the current workflow.
Its 42 input vertices become 52 stored vertices and 34 triangles, using 4 batches.
Stored vertices may repeat between materials and bounded render batches.
The original 36-vertex/22-triangle model remains the reversible baseline. The
Current v1.24.1 output adds 1,144 B of shared model storage in game and 224 B of ROM storage.
These are different budgets. Both input OBJ files remain unchanged.

The old exported file has no UVs or materials. For this file, the compiler infers
the original batch/material from source face identities, nearby geometry and
orientation, then projects the source UVs onto the added surfaces. New walls
prefer source surfaces facing in the same direction, so a sign's transparent
front decal does not replace its wooden edge material. This keeps
the sign artwork and wood border; inferred appearance is approximate, so inspect
new faces before Apply. The status reports how many faces used inference.

Before v1.24.1, this sign's new walls inherited the transparent decal and appeared
partly invisible. The corrected material inference remains in the compiler.
Original vertex row identities are recognized for material inference after
conversion from compact OBJ coordinates.
Current attachment/sphere references are retained by position when switching
back to those original rows; an unmatched reference is refused instead of moved.

The supplied extrusion is small: original depth is 0–2 units; the two new caps
are at approximately 3.72 and 3.80, both rounding to 4 game units. Height and width
are unchanged. A side view or **Textures off** shows the difference most clearly.

This sign has separate, overlapping board and transparent “60” decal faces.
The supplied edit extrudes the decal faces; the opaque white board stays at its
original depth. The lettering can therefore sit in front of the backing even
after the new walls receive wood material. To thicken the board with a flush
white front, edit/extrude both coincident front layers together in Blender.
The importer retains the OBJ's geometry; it does not invent a new backing face.

## Choosing an import mode

| Mode | Behavior |
|---|---|
|Automatic (reshape / static rebuild)|First tries the original position-only importer. If topology changed, attempts a static rebuild.|
|Reshape positions only|Retains counts, indexed connectivity, materials and mapping. Extrusions are refused.|
|Rebuild static topology|Always rebuilds the static mesh and imports its named batch materials/UVs/colors, even if counts match.|

Automatic mode preserves the existing fast reshaping workflow. Use the explicit
rebuild mode when changing materials/UVs with unchanged topology. Changing a
clip-bearing model's counts is rejected rather than dropping its animation.

Imports are drafts. Until Apply, the session, history and course viewport remain
unchanged. All pending models/clips apply together as one undo step. Closing
discards unapplied drafts. Undo/Redo, restoring the original model and project
reopening also restore GPU topology. Ordinary numeric XYZ/RGBA/UV/reference edits
remain available on an imported model. **Restore original model + clips (draft)**
stages the original layout for Preview/Apply.

## Blender settings for future object edits

Export a fresh OBJ from this model window first. Static exports now carry vertex
colors, UVs and **`batch_0`, `batch_1`, …** material names. Each name identifies
one existing texture/lighting/render signature in the current model. Texture
images remain in the ROM; the OBJ does not export a PNG/MTL artwork package.
The [Texture Browser](IMAGE_ASSETS.md) can export/edit the actual PNG artwork.

Use the same axes/scale as the [Blender track guide](BLENDER_TRACK_GUIDE.md):

- Import: Forward **−Z**, Up **Y**, scale 1, Clamp Bounding Box 0; disable Split by
  Object/Group and Validate Meshes to retain loose reference vertices.
- Reshape, extrude, add or delete faces on a **static** model. Assign the new
  surfaces an existing `batch_N` material. UV unwrap those faces as desired.
- Keep vertex row identities for existing attachment/collision center vertices.
  Their positions can move, but reordered/deleted reference rows cannot be
  automatically retargeted by meaning.
- Export only the intended object, Forward **−Z**, Up **Y**, scale 1. Enable
  **UVs**, **Colors**, **Materials** and **Triangulated Mesh**. Disable animation,
  curves/NURBS and PBR extensions. Apply only modifiers whose resulting geometry
  you intend to import.
- Retain the exported `batch_N` names. Renamed or unknown material names are
  refused. To edit the texture pixels, use the existing Texture Browser.
- For a file carrying explicit UV/material changes, choose **Rebuild static
  topology** on import. Preview before Apply.

These options were checked against installed Blender 4.4.0 using models 0, 256 and 260.
Batch names, UVs and vertex color data survived the actual Blender round-trip.

The parser accepts triangles and convex planar polygons, up to 64 corners, and
triangulates them. Triangulate concave, collinear or nonplanar polygons in Blender
first. XYZ is multiplied by100 before rounding to signed 16-bit model units. Triangles collapsing after rounding
are rejected. Existing repeated-index anchor faces may be omitted; their
referenced positions are rebuilt separately when needed.

## What is retained and rebuilt

The original serialized model is retained once as a protected prefix, including
its texture table, old arrays and opaque/unknown bytes. New active vertex,
triangle, sentinel-batch and reference arrays append at 16-byte boundaries.
Rebuilding again uses the original prefix rather than nesting previous imports.
This deliberately retains some unused bytes in exchange for preserving data we
cannot safely discard.

Existing texture IDs, count, flags/frame choices and lighting signatures remain
available through the source batch materials. Render batches use
**24 vertices / 16 triangles**, matching the stock data. The command field can
encode 32 vertices, but the local builder and stock assets use a 24-vertex boundary.
Opaque batches precede
translucent ones. Uniform transform-matrix selection is retained; a model with
a mixed matrix region within a batch would be refused rather than guessed.

Models with no clips can still have an unused animated-vertex mapping. The
compiler disables that mapping in the new active geometry; section 30 clip
ranges remain unchanged. Models with animation clips require a later retargeting
scope and keep their current fixed-topology editor.

Attachment/sphere slots are retained and remapped to the corresponding input
vertex rows. Unused reference positions receive hidden, non-colliding anchor
records. A hidden normal anchor preserves a shaded-instance allocation kind
when a stock model only has lit reference geometry. Source literal vertex bytes
are retained or interpolated unless the OBJ supplies colors. Game lighting
still computes the source model's normals at load time.

The broad-phase distance expands conservatively to the new local extent while
retaining a larger existing value. It is separate from sphere radii and still
depends on object scale/behavior. Unknown compiled vertex-index uses, vehicle
assembly logic and collision responses are not automatically retargeted.

## Budgets and limitations

Editor bounds are **4 MiB OBJ**, **4,096 input/stored vertices**, **2,048 stored
triangles including anchors**, **512 batches** and **256 KiB decoded model**.
These bound the importer; they are not proven free-memory allowances for every
game scene. Core source fields also impose signed 16-bit coordinate/index/count
ranges and signed s10.5 UV storage.

The report separates:

- Shared decoded allocation: model bytes + 0x80 plus generated normal storage.
- Per shaded-instance allocation versus the 36-byte basic instance.
- Upper bounds for normal-generation scratch and optional collision facets/
  planes, which the game builds when a behavior needs them.
- Compressed ROM growth and exact remaining trailing padding, including all
  other project edits and retained tables.

The source-sized in-place inflater check uses decoded length + 0x80, with input
lookahead/overwrite and 0x2800 Huffman workspace checks. It does not use the
unrelated 0x3000 object-map staging limit. Existing IDs mean no additional unique
model-cache slots, but scene residency, per-instance memory, allocator slots,
frame commands and performance still need your game test.

## Project and ROM export

Rebuilt models use **version 15** projects with bounded, hashed `object_rebuilds`
records. Fixed mesh/clip edits keep version 14 when no static rebuild is present.
Versions 1–14 retain their earlier writer permissions. Other course names, shared
headers, structural maps, imported courses, artwork and annotations coexist.
See [PROJECT_FORMAT.md](PROJECT_FORMAT.md).

Only edited model entries and their section 28 subtable rebuild. Untouched model
entries, table tail bytes, clip assets/ranges and unrelated sections retain their
contents when the master LUT relocates sections. The original ROM remains read-only.
No review ROM is generated or emulator launched automatically. Your gameplay
checks should cover appearance, object interaction/collision, transitions and
any scenes sharing the modified model.

Local evidence: `tools/dkr_assets_tool_src/fileTypes/objectModel.hpp`,
`include/structs.h:ObjectModel`, `include/f3ddkr.h:gSPVertexDKR/gSPPolygon`,
`src/objects.c:render_mesh/shade_model`, `src/object_models.c:object_model_init`,
`model_instance_init`, `model_init_normals` and `model_init_collision`.
