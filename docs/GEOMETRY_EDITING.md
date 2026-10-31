# Existing track geometry

Reshape existing track vertices and faces in the inspector's **Geometry → Mesh** view. Counts,
triangle indices, batches, segments and serialized collision/visibility metadata
stay unchanged. Use **Import OBJ…** to replace the mesh with new topology.

## Workflow

1. Open a ROM/project, choose a level, then **Geometry → Mesh** in the right
   inspector. Choose **Vertices** or **Faces** and a segment.
2. Select rows (Ctrl/Shift for several), or enable **Select and move geometry in
   viewport** and click a vertex or face. Ctrl-click toggles a row in the current
   segment. Vertex targets have a logical-pixel margin and terrain occlusion/
   backface/hidden-batch checks. Face picking selects the closest visible hit.
3. Move with the viewport's XYZ arrows, drag its center in the view plane, use
   XYZ nudge buttons and Step, or edit the rounded selection-center coordinates.
   A vertex row's XYZ is also editable. Moving faces translates their vertices;
   it does not alter triangle indices or UVs.
4. All copies at the same **original** XYZ move together across batches and
   segment seams. The Linked column and summary show this automatic expansion.
5. A mouse preview changes the viewport only. Release commits one undo step;
   Escape/focus loss cancels it. Invalid pointer positions retain the last valid
   position with an explanation. Ctrl while dragging uses Step snapping.
6. Ctrl+Z/Ctrl+Y and **Revert this model’s geometry** are available. Material and
   minimap reverts are independent. Save a `.dkrproj`, then export a new ROM for
   your driving/collision/visibility test. Shared levels are listed at the top.

Camera speed/framing and segment isolation survive edits. No toolbar row is
added. Object positions, racing paths, minimap artwork and course height do not
move automatically. Surface placement queries and projected scenery refresh
after commit.

In Faces mode, **Edit face material…** opens the first selected face under
**Geometry → Materials**. The whole batch is highlighted beside its texture
thumbnail and driving surface. **Change this batch’s material…** opens the
visual picker; **Edit shared material…** changes all uses of a course material.

**Verify stock rebuild…** opens the original-ROM reconstruction report
and optional stock export. It retains current project edits separately; see
[STOCK_TRACK_REBUILD.md](STOCK_TRACK_REBUILD.md). For replacement geometry, use **Import OBJ…**.

## Supported envelope

A logical vertex stays inside **every owning segment's original stored box**
and on the same side of each BSP split in that segment's stock leaf path.
Vertices exactly on splits stay on them. Existing model bounds, segment boxes,
BSP and PVS rows remain byte-identical as a fixed spatial envelope; they are
not tightened around local deformations. No visibility compiler is invented.

Generated water and vertices on faces with unresolved non-edge collision
smoothing references are protected, including their linked copies. A move
cannot merge distinct vertices, split coincident copies, overflow signed16,
collapse a triangle or reverse its normal. Both double-precision orientation
and the source float32 collision-plane arithmetic are checked. Rejected edits
are atomic.

The editor does not detect every self-intersection or recompute occlusion.
Large sight-line changes can expose stock PVS limitations even within a box.
Paths and minimap artwork may need manual adjustment. User drive/collision/
visibility tests precede claims that a particular reshaped course works.

## Verified format and runtime dependencies

Authoritative local sources:

- `include/structs.h:639,693,719,729,737`: facet rows8 bytes (`>4H`: base-plane
  index plus three neighbors); segment0x44, Vertex10 (`>hhhBBBB`), Triangle16.
  Segment+0x14 points to facets. Boxes12 (`>6h`), BSP nodes8 (`>hhBBh`).
- `src/tracks.c:1985–2051`: BSP traversal order and segment+0x28 PVS-row offset.
  These values remain protected.
- `tracks.c:2832–2920`: fixed0x82A00 track heap, decompression/pointer fixups,
  then aligned grid-mask, collision-plane and water-index allocations after
  `modelSize`. The allocation formula is checked for all55 stock models.
- `tracks.c:2981–3061`: per-face eight-by-eight XZ broadphase masks regenerate
  from current XYZ and the retained segment boxes.
- `tracks.c:3063–3222`: float32 base planes regenerate from triangle positions.
  Saved facet links guide edge bisectors. Shared-edge endpoints are retained by
  linked editing; unresolved smoothing relationships stay protected.
- `tracks.c:2923–2944`: water batch indexes/height regenerate. This milestone
  protects those vertices instead of rebuilding their wave dependencies.

Runtime size uses all generated collision planes as an upper bound even when
a game mode requests fewer. Edited streams stage at
`align_down(0x82A00 - stored_size,16)`; export checks separation from inflated
data and the source-model inflater's access order/Huffman capacity. No extracted
binary is embedded in the application.

## Projects, export and verification

Geometry overlays use **version8**, section27 `rare-decoded` byte patches and
the original-asset hash. Structural rows can coexist. Versions1–7 stay readable
with their earlier permissions: old projects cannot add XYZ patches. Without
geometry edits, saves still use v7 for structural maps or v6 otherwise. Counts,
offsets, facet rows, boxes, BSP/PVS and unknown bytes stay protected in v8.

Export rebuilds the model/master tables, reports changed XYZ/shared levels,
retains ROM length/untouched entries, recomputes CRCs and refuses original-ROM
overwrite. No-edit export is byte-identical. OBJ uses edited positions.

Verification:947 tests passed in162.89s, including69 new geometry tests.
Native RTX4060 GL3.3 real picking/numeric/mouse history/GPU/v8 checks and normal
launch pass. Results are in compact STATUS.md. Ignored evidence includes
`artifacts/phase22-stock-audit.json`, `phase22-profile-audit.log`,
`phase22-core*.log`, `phase22-native.log`, `phase22-pytest-final.log` and
`verify_geometry22.py`. No emulator or persistent sample ROM was generated.
User gameplay confirmation is pending.
