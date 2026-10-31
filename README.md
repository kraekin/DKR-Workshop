# DKR Workshop

**v0.26.0 · Public beta**

DKR Workshop is a desktop editor for Diddy Kong Racing on Nintendo 64. Open an
original **USA Rev 1 / USA 1.1 (`us.v80`) ROM**, edit courses and shared assets,
save a project, and export a separate edited ROM. Game artwork is loaded from
your ROM; it is not bundled with the application.

## Getting started

Python 3.11+ and an OpenGL 3.3 Core desktop graphics driver are required.
From the project directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m src.main
```

If activation is unavailable, use `.\.venv\Scripts\python.exe` instead of
`python`. Open your ROM with **File → Open ROM…**, then select a level on the
left. `.z64`, `.v64` and `.n64` byte orders are accepted and normalized in memory.
Editing requires the original USA Rev 1 identity; other supported sources are
view-only. Opening a modified ROM does not restore a project's editing history.

## Saving and exporting

- **Save Project** (`Ctrl+S`) writes a `.dkrproj` containing edits and the original
  ROM identity. Keep the project and original ROM to resume editing.
- **Open Project** (`Ctrl+Shift+O`) restores those edits. If the original ROM has
  moved, open it first, then reopen the project.
- **Save As Edited ROM…** (`Ctrl+Alt+S`) writes a separate big-endian `.z64`,
  rebuilding changed assets and checksums. It refuses the original ROM's path.
  Exporting the ROM does not save the editable project.
- **ROM Budget and Project Changes…** shows the exact storage budget, changed
  assets and known shared uses. ROM padding is storage space, separate from
  the game's runtime RAM and object pools.

Undo/Redo (`Ctrl+Z`, `Ctrl+Y` or `Ctrl+Shift+Z`) spans objects, assets and levels.
The title's asterisk marks unsaved project changes. Shared assets can affect
several courses; review their listed uses before applying changes.

## Viewport and navigation

| Control | Action |
| --- | --- |
| Right mouse + drag | Look around |
| Middle mouse + drag | Pan in any view |
| Alt + right mouse | Orbit around the view target |
| W/S, A/D | Move forward/back and strafe |
| Q/E | Move down/up |
| Shift | Boost movement speed ×4 |
| Wheel | Zoom |
| F | Fit the course or isolated segment |
| Escape | Cancel a gesture or release camera capture |
| Double-click an object row | Focus that object |

The camera toolbar selects **Perspective**, **Top**, **Front** or **Right**.
Its speed slider remains independent of selection and zoom. Render controls
include textures, vertex colors, wireframe, segment bounds, backface culling,
sprites, models, object markers and racelines. Markers and paths remain visible
through surfaces for editing; physical artwork respects scene depth.

### Working grid and axes

The grid uses world-coordinate multiples near the course, rather than a plane
centered on the world's origin. Spacing adapts to zoom and is shown in game units.
Automatic visibility shows it in orthographic views and hides it in Perspective.
Click **Grid** to override visibility; use its arrow menu to restore Automatic,
follow the selection's height/depth, click a track surface to position the plane,
or reset the working plane. Surface placement changes only the editing guide.

The **Axes** button toggles the small corner XYZ orientation indicator:
X red, Y green, Z blue. It follows camera orientation without covering the track.

**Help → Camera Controls** lists controls. **Help → Graphics / GPU…** identifies
the active graphics device and Python executable. On Windows, use that executable
in system Graphics Settings to choose a dedicated GPU, then restart Workshop.

## Editing tools

The right inspector has **Level**, **Objects**, **Geometry**, **Settings** and
**Tools** tabs. Larger editors open in their own windows from the **Edit** menu.

| Location | What it edits |
| --- | --- |
| Objects | Placed objects, coordinates, typed parameters, raw bytes, add/duplicate/delete |
| Geometry → Mesh | Existing track vertices/faces, linked seams and OBJ track replacement |
| Settings | Saved level defaults, references, fog, vehicles, laps and related settings |
| Tools → Placement | Group transforms, snapping, alignment and surface placement |
| Tools → Routes | Checkpoint AI lanes and directed AI-node links |
| Geometry → Materials | Visual batch material assignments, shared course materials, UVs, colors and rendering |
| Tools → Minimap | Map sprite, offsets, marker alignment, tint and PNG shortcut |
| Tools → Cinematics | Actor/camera path nodes, timing, events and preview |
| Edit → Course Builder… | Clear placed objects, draw checkpoints and create a start grid |
| Edit → Course Names… | Existing English, German and French course names |
| Edit → Texture & Sprite Browser / PNG… | PNG export/replacement, sprite anchors and texture timing |
| Edit → Global Object Properties… | Shared object definitions and compatible artwork references |
| Edit → Object Models & Animation… | Shared model vertices/UVs, static topology and animation clips |

### Objects and parameters

**Add…** opens a visual catalog with ROM-derived thumbnail cards, name/ID/category
search, category filters and a larger sprite or interactive 3D artwork preview.
Choose a target map, position and template, then Add. See
[Visual object catalog](docs/VISUAL_OBJECT_CATALOG.md).

Click artwork, a marker or an object row to select it. Use Ctrl-click for a group.
Drag the RGB arrows or center handle to move it, or use the inspector's XYZ and
Step controls. A drag is one undo step; Escape or focus loss cancels it. Ctrl-drag
snaps to Step. Supported objects also offer rotation and scale handles.

Double-click a parameter value to edit it. Descriptive names and tooltips explain
fields whose meanings are verified from the game code. Tooltips retain the
original source key and units. Unresolved fields remain **Unknown** with their
byte offset. Padding and bytes with no identified reader are labeled separately.
Names are display labels; stored keys and offsets remain compatible with projects.

**Edit raw parameter bytes / bits** exposes bytes from offset `0x08` onward.
Values accept decimal, `0x` hex or `0b` binary; arrays use comma-separated integers.
Object IDs and entry lengths remain protected in the raw editor. **Add…**,
**Duplicate** (`Ctrl+D`) and **Delete** (`Ctrl+Delete`) manage complete entries.
Templates preserve known stock values where available. The game still has finite
shared runtime pools; exact ROM capacity does not guarantee a scene's RAM usage.

### Materials

Open **Geometry → Materials**, click part of the track to select its whole batch,
and choose **Change this batch’s material…**. A resizable thumbnail picker previews
existing course materials before **Apply**; **Cancel** restores the current view.
The panel shows its texture, driving surface and affected face count together.

**Edit shared material…** changes a texture reference and/or driving surface for
all batches using that course material. **Edit texture image…** opens the PNG
browser for shared pixel edits. Each operation displays its scope. UVs, vertex
colors and rendering flags are under the expandable advanced controls.
See [Track materials](docs/TRACK_MATERIALS.md) for the complete workflow.

### Tracks and Blender

Use **File → Export Wavefront OBJ…** to export track geometry, MTL materials and
PNG textures. For replacement, select the target course, open **Geometry → Import
OBJ…**, review its preview/materials/resource report, and Apply. The dialog shows
its target course. Track replacement leaves placed objects to be aligned with the
new course; **Course Builder** can clear them or rebuild checkpoints and starts.

Track and object-model OBJ exports use compact **×0.01** coordinates. Leave
Blender import/export **Scale at 1**. Track import defaults to a **100** multiplier;
object-model import restores **×100** automatically. Numeric editor fields and
animation JSON retain game units. Use fresh exports with this scale convention.

Static object meshes support added/extruded faces. Animated models retain their
existing topology and animation groups. The model editor has its own preview and
staged Apply workflow. Track faces use batch texture assignments; changing one
batch can affect several faces. Driving surfaces are separate material data.

## Artwork and animation preview

**Sprites**, **Models** and **Special art** control artwork independently of
logic markers. Play, Rewind and the time slider preview model clips, supported
sprite sequences, actor paths, fish/butterflies, texture motion and approximate
water. **Scene** selects a cinematic channel alongside ambient actors. Selected
clip overrides and preview toggles do not change saved data.

The viewport previews supported graphics and paths. It does not run the game:
AI, progression scripts, audio, particles, physics and some live camera/racer
substitutions are not simulated. Model lighting and water are approximations.
Use the exported ROM in your emulator or on hardware to assess gameplay.

## Guides

- [Blender track creation and export](docs/BLENDER_TRACK_GUIDE.md)
- [Course Builder](docs/COURSE_BUILDING.md) and [course names](docs/COURSE_NAMES.md)
- [Object placement](docs/PLACEMENT_TOOLS.md) and [object creation](docs/OBJECT_EDITING.md)
- [Checkpoint fields](docs/CHECKPOINT_FIELDS.md), [AI nodes](docs/AI_NODES.md)
  and [route fields](docs/ROUTE_RESEARCH.md)
- [Verified parameter labels](docs/PARAMETER_LABELS.md)
- [Track geometry](docs/GEOMETRY_EDITING.md), [segmented import](docs/SEGMENTED_TRACK_IMPORT.md)
  and [custom artwork](docs/CUSTOM_TRACK_ARTWORK.md)
- [Materials and driving surfaces](docs/TRACK_MATERIALS.md)
- [Texture/sprite PNG workflow](docs/IMAGE_ASSETS.md) and [minimap settings](docs/MINIMAP_SETTINGS.md)
- [Global object properties](docs/GLOBAL_OBJECT_PROPERTIES.md),
  [object models/animation](docs/OBJECT_MODEL_EDITING.md) and [static model import](docs/STATIC_OBJECT_IMPORT.md)
- [Level settings](docs/LEVEL_SETTINGS.md), [environment preview](docs/ENVIRONMENT_PREVIEW.md)
  and [cinematic paths](docs/CINEMATIC_PATHS.md)
- [Runtime memory snapshots](docs/RUNTIME_CAPACITY.md)
- [Editing the Python code](docs/CODE_EDITING_GUIDE.md),
  [binary format reference](docs/FORMAT_REFERENCE.md) and [project format](docs/PROJECT_FORMAT.md)

## Development

All application code lives in `src/`. `src/core/` contains headless data/editing
logic; `src/renderer/` handles OpenGL and camera behavior; `src/ui/` contains Qt
widgets. The local decomp checkout provides authoritative format references.
No proprietary ROM data belongs in source control.

```powershell
python -m src.main --rom "your-original-rom.z64" --level 5
python -m src.main --project "my-course.dkrproj"
python -m pytest -q
```

ROM integration checks use a locally supplied original ROM; they skip when it
is absent. Synthetic parser tests need no game data. Native graphics checks
require a desktop display. Current verification is recorded in [STATUS.md](STATUS.md).
Historical implementation plans and audit reports are retained under `docs/`
as development records, separate from this usage guide.
