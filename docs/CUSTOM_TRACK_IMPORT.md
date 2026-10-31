# Small custom-track import

This page documents the original v1.17.0 single-segment mode. v1.18.0 adds
Automatic and Spatial segments modes, larger meshes and per-material surfaces;
see [SEGMENTED_TRACK_IMPORT.md](SEGMENTED_TRACK_IMPORT.md) for the current workflow.
Single segment mode retains the bounds below.

Current track exchange (v1.25.5): suite exports XYZ at1/100 size; Blender
import/export Scale1; suite import multiplier100 restores game units before
rounding/collision. Offsets remain game units. Historical sample files below
are unchanged raw-coordinate assets and use explicit multiplier1.

For current Blender authoring/export instructions, use the
[Blender track guide](BLENDER_TRACK_GUIDE.md), including Automatic/Spatial
segmentation and custom MTL/PNG artwork.

v1.17.0 adds **Geometry → Import OBJ…**. Select a target level, open your OBJ,
choose the scale/XYZ offset and map each OBJ material to an existing texture
slot. The independent preview supports the usual RMB/WASD/F camera controls.
It can overlay existing objects and racing lines. Changing an option disables
Apply until **Build preview** succeeds again. Apply replaces the shared track
model as one undo step. Cancel and rejected imports preserve the current project.

Save a `.dkrproj` and use the normal edited-ROM exporter for your gameplay test.
The original ROM remains read-only. No ROM is created by opening/building the
preview. **Restore stock track** returns the complete model to its original ROM
state (geometry, materials and minimap settings) as one reversible operation.
The existing individual revert buttons return their respective fields to the
import baseline. Objects and other asset edits have their own history.

The user-requested local sample is in
`artifacts/samples/ancient-lake-test-track/ancient-lake-test-track.obj`, with a
README and rendered previews beside it. Select Ancient Lake, import the file,
and use Scale1, offsets0 and the default material mappings. Its 462-triangle road
follows the existing car checkpoint route and covers all eight starting spots.
Existing scenery/pickups and the minimap retain their stock placements/artwork.
The sample has passed compiler, floor-coverage, budget and native preview checks.
The user also completed a race on it in place of Ancient Lake with no reported
issues, completing the representative23B gameplay gate. The user subsequently
authorized23C, now implemented as described in the segmented import guide.
Its inherited surfaces are slot6 default/road (road and center stripe), slot0
grass (shoulders) and slot1 stone (walls). Tools → Materials → Textures lets you
change a slot’s surface independently of its image; all faces using that slot
share the new surface. Standard OBJ does not carry DKR surface codes.

## Preparing a mesh

- Y is up; compact OBJ coordinates are multiplied by100 by default. Game XYZ
  rounds to signed16 integers after scaling and game-space offsets. Scale
  and translate your mesh into the target level’s coordinate range. A useful
  first test is a small replacement road/platform near the existing start.
- Up to **499 triangles in one segment**. This guarantees every face fits the
  game’s 500-entry collision candidate array, including its segment marker.
  Use [segmented import](SEGMENTED_TRACK_IMPORT.md) for larger tracks.
- UTF-8 OBJ, at most 4 MiB and 20,000 input vertices. Positive and negative indices,
  vertex RGB/RGBA colors in 0..1, UVs and normals are read. Normals are recomputed
  for collision. Triangles and planar convex polygons work; triangulate concave,
  collinear or nonplanar polygons in your modeling application first.
- Shared edges must have consistent, opposite directed winding. Degenerate,
  duplicate and nonmanifold triangles are refused after coordinate quantization.
  Road faces should face up. **Reverse face winding** reverses both render and
  collision orientation. **Draw both sides** changes rendering; collision retains
  the face’s normal/orientation.
- UVs use OBJ’s V convention and convert to signed s10.5 texels using the assigned
  texture’s dimensions. Excessive tiling is refused. Missing UVs receive a local
  dominant-axis projection per triangle; supply UVs for intentional artwork.
- `usemtl` names map to existing ROM texture slots. `slot_N` and the exporter’s
  `texture_ID_frame_N` names get suggested mappings. Review every mapping.
  External MTL/PNG files are not imported here. Use the Texture & Sprite Browser
  to replace ROM artwork, and Tools → Materials for surfaces, UVs and colors.
  Group/object/smoothing names do not create segments.

## Retained data and alignment

Replacement affects every level referencing the target geometry ID; those levels
are listed before Apply and in the export report. Existing texture slots and
their driving surfaces remain available, even when a slot has no imported faces.
Current minimap settings and slot assignments survive importing.

Objects, player starts, checkpoints, AI paths, scripted animation paths, minimap
artwork and level settings keep their existing values. They are not automatically
retargeted to the new mesh. Use their editors to align them before racing.
The preview overlay helps assess placement; a valid mesh alone is not a playable
race. Static geometry is compiled. New animated wave geometry, segment-specific
water behaviors and larger segmented layouts need later compiler work. This
milestone replaces existing models; it does not add level IDs or save slots.

## Compiler and validation

All formats come from the local matching decomp:

| Data | Source / emitted form |
|---|---|
| Header/segment | `include/structs.h`:76 /68 bytes, big endian |
| Vertices/faces/batches |10 /16 /12 bytes; max24 vertices and16 faces per batch (local `buildModelBatch.cpp`; original Rev1 assets) |
| Collision facets |8-byte base/neighbor rows, welded by quantized XYZ across batches/colors/materials |
| Collision candidate bound | `src/collision.h:7`, `src/hasm/collision.c:120–178`:499 faces +1 marker |
| Visibility/BSP | Self bit1, zero BSP nodes; `src/tracks.c:1741–1764` explicitly supports one segment |
| Runtime dependencies | `src/tracks.c:2832–3222`: grid masks, base/edge planes, reciprocal bit15 and aligned allocations |
| Track heap/compression |0x82A00 bytes; production Rare gzip compressor and source inflater overlap audit |

The compiler groups opaque batches before translucent batches, retains real
texture slots, and writes a zero-padded canonical layout with runtime members
zeroed. Bounds contain the original level envelope plus imported geometry and
vertical margin, checked against signed16 grid overflow. New geometry has no
wave/animated batch flags. Shared edges use neighboring face ordinals; boundary
edges use their own face. Runtime loading builds the planes and grid from these
records. Folded edges that collapse a bisector are refused.

Apply checks the combined project’s actual compressed ROM layout before changing
history. Export uses the existing bounded assembler, unchanged-asset preservation,
N64 checksums and atomic file publication. v9 projects store original asset hashes,
an independently validated compiler baseline and current fixed-topology edits;
reopening does not depend on the OBJ file. See [PROJECT_FORMAT.md](PROJECT_FORMAT.md).

Automated verification covers parsing/refusals, all 55 original target templates,
499-face batching, slopes/closed surfaces, collision-plane containment and
reciprocal edges, canonical tamper rejection, edit/history/project coexistence,
ROM budget failures, in-memory ROM/OBJ output and untouched assets. Native checks
cover the actual dialog, its separate GL preview, cancellation, failure, Apply,
topology/GPU refresh, numeric geometry edits, project reopen and stock restore.
The user completed the representative single-segment gameplay gate. The larger
segmented compiler has its own collision, camera, race and performance review.
