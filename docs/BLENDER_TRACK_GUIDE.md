# Making custom DKR tracks in Blender

For **DKR Editing Suite v1.25.5**, targeting **USA Rev 1**. The export settings
below were checked with the locally installed **Blender 4.4.0**, using a real
OBJ/MTL/PNG export and the editor's existing importer/compiler.

The workflow is: **model in Blender → export OBJ + MTL + PNGs → import and
preview in DKR Editing Suite → align gameplay objects → save a project and
export a ROM**. Keep the `.blend` file as your editable source.

## Quick export preset

In Blender, select only your custom track meshes, then choose
**File → Export → Wavefront (.obj)**. Save these settings as an operator preset
using the preset control in the export options, if desired.

| Blender export option | Setting for this editor |
|---|---|
| Selected Only / Export Selected Objects | **On** |
| Scale | **1.000** |
| Forward Axis | **−Z** |
| Up Axis | **Y** |
| Apply Modifiers | **On** |
| Properties / evaluation mode | **Viewport** |
| UV Coordinates / Export UVs | **On** |
| Normals / Export Normals | **On** |
| Colors / Export Colors | **Off** for your first track |
| Triangulated Mesh / Export Triangulated Mesh | **On** |
| Materials / Export Materials | **On** |
| PBR Extensions | **Off** |
| Path Mode | **Copy** |
| Animation | **Off** |
| Curves as NURBS | **Off**; export actual meshes |
| Object/material/vertex/smooth groups | Leave off; the importer generates segments |

The preset was verified against Blender 4.4's export operator. Copy mode puts
referenced images beside the export; images must already be saved as PNGs.
The triangulation option changes the exported mesh without changing your
editable mesh. [Blender 4.4 export API](https://docs.blender.org/api/4.4/bpy.ops.wm.html#bpy.ops.wm.obj_export).

## 1. Start with a reference at the correct size

Start with a fresh export from the editor as a size and placement reference:

1. In DKR Editing Suite, select the level you will replace.
2. Choose **File → Export Wavefront .OBJ…** and export into a reference folder.
   Keep the generated OBJ, MTL and texture folders together.
3. In Blender, use **File → Import → Wavefront (.obj)**. Set **Scale 1**,
   **Forward −Z**, **Up Y**, and **Clamp Bounding Box 0** (disabled).
4. Put the imported reference into its own collection, for example `REFERENCE`.
   Leave it at its imported world position. Build your custom meshes in a
   separate collection, for example `CUSTOM_TRACK`.
5. When exporting, select only your new meshes. The reference is for measuring
   and placement; exporting it too can create overlapping/duplicate geometry.

The editor's OBJ export contains the track geometry. Trees, pickups, starts,
checkpoints and other placed game objects are edited separately in the editor.
The original track is useful as a reference; the custom importer applies
stricter topology checks, so an untouched stock OBJ is not a promised rebuild.

## 2. Scene units, axes and visibility

Use **Scene Properties → Units: None**, with unit scale **1**. Track OBJ files
now use **one Blender/OBJ unit for 100 game units**. The editor exports XYZ at
**×0.01** and its track import **Scale (OBJ → game)** defaults to **100**.
Leave Blender's import and export scales at **1**. This is a convenient editing
scale, not a physical-meter measurement. Internal editor geometry and objects
still use game coordinates. A **0.01** Blender-unit change becomes **1** game unit.

Model normally in Blender with **Z pointing up**. The export preset handles
the conversion to DKR's **Y-up** coordinates. Do not also rotate the entire
course by 90 degrees. Blender documents **−Z Forward / Y Up** for this axis
conversion. [Blender OBJ axes](https://docs.blender.org/manual/id/4.4/files/import_export/obj.html).

| Blender world coordinate | DKR/editor coordinate after export |
|---|---|
| X | X ×100 |
| Z, height | Y, height ×100 |
| Y | −Z ×100 |
| Example: `(-18, 70, 0.24)` | `(-1800, 24, -7000)` |

Building over the reference retains useful alignment with existing objects.
Building around Blender's origin is also possible, but you will need to move
the starts, checkpoints and scenery, or deliberately set import offsets.

A full track can exceed Blender's default viewing distance. In the viewport's
**N sidebar → View**, try **Clip Start 0.01** and **End 1000**, then adjust to
your course. These are modeling-view suggestions and do not affect the export.
The clip distances control which geometry the viewport displays.
[Blender viewport clipping](https://docs.blender.org/manual/id/4.4/editors/3dview/sidebar.html).

### Compact track sizes

The new exchange convention makes tracks 100 times smaller in Blender while
preserving their world origin. Measured horizontal extents at the new scale:

| Track | Width × length |
|---|---|
| Flat Oval starter, compact generation | 64 × 48 |
| S-Bend Loop starter, compact generation | 67.08 × 56 |
| Gentle Hills starter, compact generation | 62 × 48 |
| Ancient Lake, new export | 58.95 × 105.11 |
| Central Area, new export | 148.03 × 128.88 |

Select the imported track meshes and use **Numpad .** to frame the selection.
Moving a stock reference to the origin changes alignment with existing game
objects. The editor performs no centering or unit guessing.

Existing `.blend`, OBJ and project files are not rewritten. Earlier supplied
starter/sample files contain raw game coordinates; their original instructions
use editor import Scale1. For the new compact workflow, use a fresh suite export
or generate compact starter files with the updated generator. Object-model OBJ
exchange also uses this1:100 scale from v1.25.6, with automatic×100 import; its
[topology and animation rules](OBJECT_MODEL_EDITING.md) remain separate.

Fresh [compact starter files](../artifacts/samples/blender-starter-tracks-compact/README.md)
are available for the new default. To regenerate their `.blend`/OBJ files, run the helper from the
project root in a separate background Blender process:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe' --background --factory-startup --python artifacts/build_blender_starter_tracks.py
```

It writes `artifacts/samples/blender-starter-tracks-compact/`, using the existing
starter source data/artwork. Earlier starter files are left in their original folder.

## 3. Build the road and surroundings

Start with a simple road loop and shoulders. Use the reference's road width
and corner sizes as a guide. Add enough cross-sections for curves and slopes,
then add walls, banks or scenery after the basic road works.

- Keep the mesh low-poly. Count **triangles after modifiers**, rather than
  Blender's quad count. A quad normally becomes two triangles.
- Quads are convenient while modeling. Enable export triangulation, and use a
  Triangulate modifier when you want to inspect/control the diagonals before
  export. Curved/nonplanar quads can change the driving surface depending on
  which diagonal is used.
- Avoid high subdivision levels and tiny bevels on a whole course. Spend
  triangles on the road shape, useful slopes and visible silhouettes.
- Make adjoining road sections meet precisely. Weld intended shared edges;
  avoid overlapping strips, duplicate faces and T-junctions. An edge joining
  two faces should be used in opposite directions by those faces.
- Open road/terrain boundaries are allowed. The entire level does **not** have
  to be a sealed, watertight solid. Edges shared by more than two triangles,
  duplicate triangles and zero-area triangles are refused.
- Several mesh objects are fine; joining everything is optional. Naming
  objects `segment_0`, etc. does not control DKR segmentation. Automatic mode
  partitions the exported geometry spatially.
- Convert curves, text and generated/instanced results into actual mesh
  geometry for export. Remove loose edges and vertices from the export copy;
  OBJ line/point/curve statements are unsupported.

The import creates **static geometry with collision** for ordinary imported
faces. A mesh named `collision` or `no_collision` has no special meaning here.
For your first course, include the road, terrain and solid walls. Place trees,
balloons, zippers and other game objects through the editor's Objects tools.
Transparent pixels do not make matching holes in a collision triangle.

### Transforms and face orientation

Before the final export, select the custom meshes in Object Mode and use
**Ctrl+A → Rotation & Scale**. This keeps their visible placement and makes
modifier behavior easier to inspect. Keep the intended world location;
clearing location would move the course. Check mirrored/negative-scale pieces
carefully. [Blender Apply transforms](https://docs.blender.org/manual/id/4.4/scene_layout/object/editing/apply.html).

In Edit Mode, select faces and use **Shift+N** to recalculate outside normals.
Inspect the **Face Orientation** overlay: the **top of the road must be its
front side**, pointing toward Blender +Z. An open road can need a manual
**Mesh → Normals → Flip** even after recalculation.
[Blender normal tools](https://docs.blender.org/manual/en/4.0/modeling/meshes/editing/mesh/normals.html).

DKR collision normals come from the actual triangle winding. Shade Smooth,
custom shading normals and the editor's **Draw both sides** option do not fix
a road whose collision orientation is inverted. The editor's **Reverse face
winding** option reverses the whole import; fix individual incorrect patches
in Blender.

Positions become **integer game coordinates** after scale/offset. Tiny details
can collapse when rounded. Inspect thin triangles and nearly coincident
vertices; use Merge by Distance with a suitably small distance when cleaning
the mesh. Work comfortably inside the coordinate limits rather than designing
against the exact signed-16-bit boundary.

## 4. Materials and driving surfaces

Create clearly named materials such as `Road`, `Grass`, `Wall` and `Sign`.
In Edit Mode, select the appropriate faces and **Assign** their material slots.
Separate materials are useful even when they share the same image: the editor
can give them different driving surfaces.

For a textured material in the Shader Editor:

1. Use a **Principled BSDF**, connected to **Material Output → Surface**.
2. Add an **Image Texture**, open a saved local **PNG**, and connect its
   **Color → Principled BSDF Base Color**.
3. Use the mesh's UV map; avoid Generated/Object coordinates and Mapping-node
   effects for this export. Put the intended placement/repetition into the UVs.
4. Keep material opacity at 1 for an opaque road. Start with a nonmetallic
   material and no extra shader effects.
5. Save edited/painted images to disk before exporting. A packed or unsaved
   Blender image alone is not a portable OBJ texture file.

OBJ/MTL import uses the diffuse PNG or a solid diffuse color. It does not
recreate Blender's lighting, World shader, metallic/roughness appearance,
normal maps or procedural node networks. Bake procedural artwork into a PNG
if you want that artwork to travel with the track. Supported MTL diffuse tint
and opacity values are multiplied into the imported pixels.

**The picture and the driving surface are separate.** A grass-looking PNG
does not automatically make grass physics. In the editor's import Materials
page, choose **Grass** for grass, **Default / road** for the road, and the
desired surface for other materials. Existing ROM slots can use **From slot**.
The importer does not infer physics from material names, and a blue PNG alone
does not create animated DKR water.

## 5. UVs and N64 texture sizes

Give the mesh an active UV map. In Edit Mode, mark seams where needed and use
**U → Unwrap**, or a suitable projection for a flat road/sign. Inspect the
image in Material Preview and the UV Editor before export.

Repeated road textures are fine: UVs can extend outside 0..1 when the material
wraps. Keep repetition modest and restart UV islands along long roads.
DKR stores UVs as signed fixed-point texels; enormous UV values are rejected.
For reference, the compiler stores `U × width × 32` and
`(1 − V) × height × 32`, each within −32768..32767.

**Do not flip the PNG for this OBJ workflow.** The importer performs the OBJ V
conversion. The Texture & Sprite Browser's upright export/reimport handling is
a separate workflow; manually flipping again here can invert the artwork.

Start with **32×32 RGBA16** textures. In the editor, each width and height can
be **8, 16, 32 or 64**, provided the chosen format fits the 4 KiB texel budget:

| Example | Texel storage | Fits |
|---|---:|---|
| 32×32 RGBA16 | 2 KiB | Yes |
| 64×32 RGBA16 | 4 KiB | Yes |
| 32×32 RGBA32 | 4 KiB | Yes |
| 64×64 RGBA16 | 8 KiB | No |

RGBA16 has 5 bits per RGB channel and on/off alpha. RGBA32 keeps 8-bit color
and alpha but uses twice the space. Larger source PNGs can be resized by the
importer; review the **N64 result**, since small-texture conversion loses detail.

- **Opaque:** normal road/walls; forces full opacity.
- **Cutout:** PNG transparency with a hard edge, such as a fence picture.
- **Blend:** partial transparency; requires RGBA32.
- **Clamp U/V off:** repeat on that axis. Turn clamp on for a single image
  that should not repeat beyond its edges.

Blender 4.4 can write an unsupported `map_d` opacity entry when a PNG's Alpha
output is connected to the material. If the editor reports an opacity-map
problem, select that material, click **Choose PNG…**, choose the same RGBA PNG,
then set **Cutout** or **Blend** and rebuild. This clears unsupported sidecar
map settings and uses the PNG's own alpha. Separate grayscale opacity maps
need their alpha combined into the diffuse PNG first.

Leave **Export Colors off** initially: absent vertex colors become white.
Later, vertex colors can provide DKR-style shading, but they multiply the
texture color. Blender lights and smooth shading are not baked automatically.

## 6. Export the files

1. Save your `.blend` and all edited PNGs.
2. In Object Mode, select only the custom mesh objects.
3. Choose **File → Export → Wavefront (.obj)** and use the quick preset above.
4. Export to a dedicated folder. Check that it contains the OBJ, its MTL and
   the copied PNGs. Keep the whole folder together when moving the source.

A useful layout is:

```text
MyCourse/
  MyCourse.blend
  textures/             # your source PNGs
  export/
    MyCourse.obj
    MyCourse.mtl
    road.png
    grass.png
    wall.png
```

Several materials can reference one image. Use distinct PNG filenames when
they are different images. Object/group names do not set checkpoint order,
surface physics, collision flags or visibility regions.

## 7. Import into DKR Editing Suite

1. Open the original **USA Rev 1 ROM** and select the level being replaced.
2. In the right pane, open the **Geometry tab → Import OBJ…**.
3. Open your exported OBJ. Keep **Scale (OBJ → game) 100**, **XYZ offsets 0**, **Automatic**
   segmentation and **Automatic cell size** when using aligned reference units.
   Offsets are game units and are added after the scale conversion; do not
   also scale up the mesh in Blender. Change the multiplier only for deliberate resizing.
   Keep Reverse face winding and Draw both sides off for a correctly made road.
4. On **Materials**, review every row. Use **New PNG / color** for your custom
   materials, or deliberately select an existing ROM slot. Check the image,
   dimensions, format, alpha/wrap and **driving surface**.
5. Click **Build preview** after changing options. Inspect the road from above
   and below, artwork/UV orientation, corners/slopes and the resource report.
   Use the existing object/racing-line overlay to check alignment.
6. Click **Apply track import** when satisfied. Geometry and new artwork form
   one undo step. Shared affected levels are listed in the dialog/report.
7. Save a `.dkrproj`. The project embeds the imported track and dedicated
   artwork, but retain the `.blend` for future shape/UV changes and reimports.

New PNG artwork uses the Automatic/Spatial compiler. The explicit
**Single segment (≤499)** mode is the older ROM-slot-only option.
The compiler generates segments, batches, collision, bounds, BSP and visibility
data; you do not manually create those in Blender.

## 8. Align the gameplay data

Importing a track retains existing objects, starts, checkpoints, AI paths,
cinematic paths, minimap artwork and level settings. For a substantially new
layout, align these in the editor before racing:

- **Tools tab → Routes → Course builder…:** place/order the closed checkpoint
  route and review headings and AI lanes. Check the vehicle's selected set.
- Use its **Start grid** controls to place all eight racers on the approach
  from the final checkpoint toward CP0. The whole grid should be before CP0's
  crossing plane, facing toward it, with floor beneath every start.
- Reposition scenery, pickups, zippers, cameras and triggers in Objects.
  Enable **Sprites** to see sprite trees and **Models** for physical models.
- Update the minimap separately. Changing the road mesh does not redraw it.
- **Edit → Course Names…** changes the displayed course name if desired.

See [Course-building helpers](COURSE_BUILDING.md) for the start-grid workflow.
Save the project, export your edited ROM through the normal File menu, and
test starts, a complete lap/race, AI, road seams, barriers, cameras and speed
in-game. Replacing geometry affects every level sharing that geometry ID;
it does not create a new level slot.

## Current practical limits

These are the current editor/compiler bounds, rather than a suggested target
for every course. A first draft comfortably below the limits is easier to edit.

| Item | Current bound / implication |
|---|---|
| Input OBJ | 4 MiB UTF-8; 20,000 input vertices; 6,000 triangles after triangulation |
| Compiled output | 6,000 stored triangles total, including clipping and hidden collision guides |
| Spatial segments | Up to 127; at most 120 ordinary collidable triangles per cell |
| Track runtime heap | 535,040 bytes, including generated collision/runtime data |
| Coordinates | Signed 16-bit integers after transform; bounds need additional margin |
| Texture allocation | Up to 4 KiB of texels per new image; RAM/ROM budgets also apply |
| Materials/assets | Up to 255 track slots including retained slots; up to 128 dedicated textures per project |

**The 499-triangle limit belongs to single-segment mode, not a whole spatial
track.** A spatial import can still run out of density, output triangles,
segments or runtime memory before reaching 6,000 input triangles. Clipping
and seam helpers can make the stored count substantially larger than the
Blender count. Let the preview report guide reductions.

Imported segments currently use conservative visibility with game frustum
culling. Avoid putting a huge amount of detail into one view. Objects, effects,
HUD and multiplayer also use the game's memory/rendering resources. The report
explains local collision-query limits; successful compilation is followed by
your normal gameplay test.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Track is huge or far parts disappear | Use a fresh compact suite export, Blender import/export Scale1, Clamp0 and frame selection. Try Clip Start0.01 / End1000. Old raw-unit files are unchanged. |
| Course lies on its side | Export Forward −Z / Up Y. Remove any extra manual 90-degree conversion. |
| Objects are elsewhere or floating | Restore intended world placement, or reposition retained objects/checkpoints/starts to the new road. |
| Parts disappear in Blender | Increase viewport Clip End to suit the course size. |
| Missing or wrong PNG | Save images; export materials with Path Mode Copy; keep OBJ/MTL/PNGs together; use Choose PNG if needed. |
| Texture reversed or upside down | Check the UV island orientation; use the preset and normal PNGs without another flip. |
| Unexpected tint/darkness | Check vertex colors and MTL diffuse tint/opacity; Blender lighting is not baked. |
| Opacity-map rejection | Choose the RGBA diffuse PNG in the import dialog, then choose Cutout/Blend. |
| Road displays but collision seems wrong | Check real face winding, positive scale, overlapping faces and retained start/checkpoint heights. |
| Duplicate/nonmanifold/degenerate refusal | Remove overlaps/duplicates and repair shared edges; tiny features can collapse during integer rounding. |
| Unsupported OBJ statement | Export meshes and remove loose edges/points; avoid NURBS/curve output. |
| UV range refusal | Reduce UV magnitudes/tiling; split long road UVs into shorter islands. |
| Density/output/heap refusal | Reduce subdivisions and small details. Automatic already tries smaller cells; object names do not change its limits. |
| Grass drives like road | Set that material's driving surface to Grass; the PNG/name does not choose physics. |

Further implementation details are in [segmented import](SEGMENTED_TRACK_IMPORT.md)
and [custom artwork](CUSTOM_TRACK_ARTWORK.md). The settings above were checked
against `src/core/track_import.py`, `track_segments.py`, `track_artwork.py` and
the current import dialog. Verification used an isolated Blender 4.4 background
process and an in-memory compile/ROM-budget check; no gameplay ROM was generated.
