# DKR Workshop 0.27.0 — creator workflow

**0.27.1 placement fix:** Add Objects now starts on visible ground in front of
the camera, prioritizing the view centre, instead of a selected object's position
or the navigation target. Lower-centre ground is used if the centre misses;
walls, hidden ground and unrepresentable positions are rejected. Explicit XYZ
edits in the catalog remain available.

- **Visual Add Objects catalog:** browse all 304 types as thumbnail cards;
  search by name, ID, category or behavior; filter categories; inspect a larger
  sprite/image or interactive 3D reference preview before placing an object.
- **Complete object mesh artwork export:** **Object Models & Animation → Export
  OBJ + artwork…** writes the current base mesh, `batch_N` MTL materials and
  referenced PNG texture frames. Static and animated models retain UVs, colors,
  vertex identities and the existing Blender Scale 1 workflow.
- **Placement correction:** changing levels during an active drag cancels that
  provisional move instead of creating an unintended undo step.

Catalog browsing and export do not change project history. Export uses pending
model drafts and applied project artwork; it does not apply those drafts.
Keep the OBJ, MTL and texture folder together. Animation clips remain a separate
JSON export, and animated mesh topology retains its existing restrictions.

The supported ROM remains original USA Rev 1 / USA 1.1. Existing project versions
and binary editing protections are unchanged. No game artwork is bundled.
Restart Workshop to load the new source; keep unsaved work safe in the current
editor before closing it.

Guides: [Visual catalog](VISUAL_OBJECT_CATALOG.md),
[Object artwork export](OBJECT_ARTWORK_EXPORT.md). Current verification is in
[STATUS.md](../STATUS.md).
