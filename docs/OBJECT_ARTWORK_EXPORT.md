# Object mesh and artwork export

Open **Edit → Object Models & Animation…**, select a shared model, then choose
**Export OBJ + artwork…**. The export contains:

- The current draft's **base mesh OBJ**, with original vertex-row identities,
  winding, per-corner UVs and RGBA values.
- A companion **MTL** defining each existing `batch_0`, `batch_1`, … signature.
- A **PNG texture folder** containing the actual frames referenced by the
  exported batches. Repeated uses share one image.

Keep the OBJ, MTL and texture folder together. Import into Blender with Forward
**−Z**, Up **Y**, Scale **1**, Clamp Bounding Box **0**, Split by Object/Group off
and Validate Meshes off. Images and materials load through relative paths, even
when the export folder contains spaces or non-ASCII characters. Companion names
are sanitized where the OBJ/MTL syntax needs them.

Both static and animated models export textured artwork. XYZ uses the same
1:100 convention as the existing object exchange: one OBJ unit equals 100 model
units. Import restores ×100. Existing loose attachment/collision rows and anchor
faces remain in the file; do not merge/reorder/delete reference rows. Blender
may discard loose rows, and the importer still refuses a missing required row.

The exported model is the base mesh even while a clip plays in the preview.
Clips export separately as JSON. This does not bake animation, assemble vehicle
parts or simulate game lighting, environment mapping, procedural effects or
behavior logic. Hidden batches retain their signatures and use transparent MTL
materials. Baked vertex RGBA is retained; lit source rows also retain their
original packed data for the existing round-trip rules.

**Source and editing**

Geometry comes from the current model draft. PNGs come from the current applied
project textures and existing frame selection. Exporting neither applies drafts
nor adds history or saves a project. OBJ retains vertex color data; its display
in an external application depends on that application's importer and material.

PNG rows match the exported UVs. The files carry the existing Texture Browser's
`dkr-asset-section=2` / `dkr-png-rows=stored` metadata, so importing one there does
not accidentally flip it a second time. An external image editor may strip that
metadata; use the Browser's **Raw ROM rows** mode for such exported image files.

The MTL is for external viewing. It does not enable new texture slots or import
arbitrary Blender materials. For static model UV/material/topology changes,
retain the `batch_N` names and choose **Rebuild static topology** on import.
**Reshape positions only** and animated model imports retain their existing
topology/material protections and apply positions only. Replace texture pixels
through the Texture Browser; editing a package PNG does not alter the project.

**Publication and format boundaries**

The existing staged track-export publisher also handles these bundles. It
encodes sidecars first, publishes the OBJ last, restores a previous MTL on
failure, and removes newly published files when publication fails. Texture
folders include a content hash, so a new export does not rewrite an old image
set. A manually modified PNG inside a matching hash folder is refused rather
than overwritten. Renaming/moving that folder or choosing a new OBJ name allows
a fresh export while retaining the edited copy.

No new ROM parser, binary writer or project version was introduced. The exporter
reuses the verified 0x58 ObjectModel header, 10-byte vertices, 16-byte triangles,
12-byte sentinel batches and TextureHeader frame selection. Local references:
`tools/dkr_assets_tool_src/fileTypes/objectModel.hpp`, `include/structs.h`,
`src/object_models.c` and `src/textures_sprites.c:material_set`.
