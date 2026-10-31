# Editing the DKR Workshop code

This guide describes the DKR Workshop source in `D:\RomHacking\n64\dkr`.
The examples below are instructions for your own edits; the application's
camera defaults have not been changed as part of writing this guide.

## 1. Open and run the project

Open the whole `D:\RomHacking\n64\dkr` folder in your code editor. The main
application is ordinary Python source, so you can save a `.py` file and restart
the application to try the change. There is no separate build step for these
Python edits and no automatic live reload.

The existing Python interpreter is:

```text
D:\RomHacking\n64\dkr\.venv\Scripts\python.exe
```

Choose that interpreter if your editor asks for one. Using a different Python
installation is a common reason for missing PySide6, NumPy or OpenGL imports.

From PowerShell, launch the editor with:

```powershell
Set-Location 'D:\RomHacking\n64\dkr'
.\.venv\Scripts\python.exe -m src.main
```

For repeated camera experiments, open the original ROM and Ancient Lake
automatically:

```powershell
.\.venv\Scripts\python.exe -m src.main --rom 'Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64' --level 5
```

Use `--level 0` for Central Area. A saved project can be opened instead:

```powershell
.\.venv\Scripts\python.exe -m src.main --project 'D:\your-folder\your-course.dkrproj'
```

`--rom` and `--project` are alternatives. Run from the project root; launching
`src/main.py` directly can cause package import problems. Save any unsaved
course work before closing your editor window to restart it. An already open
process continues using its imported Python code.

Keep a copy of files before experimenting, or use local Git commits if you
already use Git. The current folder is not an initialized Git repository.
Python indentation matters: preserve the surrounding spaces, normally four
spaces per level, and save files as UTF-8.

On a different computer with no environment yet, the initial setup is:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

You do not need to repeat installation after ordinary source edits.

## 2. How the folders fit together

```text
src/
  main.py             Start Qt, configure OpenGL, apply the theme, launch the window
  __init__.py         Application version
  core/               Game formats, editing operations, validation, projects and ROM writing
  renderer/           Camera, input, picking, drawing, GPU resources and shaders
  ui/                 Windows, dialogs, panels, menus and toolbars
tests/                 Automated checks, generally named after the feature they test
docs/                  Feature guides and verified format notes
research/              Local game source used as a reference
artifacts/             Generated logs, screenshots and temporary verification output
pyproject.toml         Dependencies, package version, entry point and pytest configuration
```

All application code belongs under `src/`. Keep using that one package.

The three main layers have different jobs:

| Layer | Typical responsibility | Example |
|---|---|---|
| `src/ui/` | A user clicks a button or edits a field; present results and errors. | `object_inspector.py` builds the object properties panel. |
| `src/core/` | Interpret or change game data; check bounds; preserve undo and export behavior. | `editing.py` owns `EditSession`, the project's edit history and overlays. |
| `src/renderer/` | Display the current data and handle viewport interaction. | `viewport.py` owns the camera and the scene's drawing/input loop. |

Core code uses Python/NumPy and should stay independent of Qt and OpenGL.
`renderer/camera.py` is also deliberately usable without a Qt or GL context.
That makes its movement and projection calculations straightforward to test.
The C files under `research/` are references: changing them will not change
this Python application or patch the loaded ROM.

## 3. Worked example: start closer to the map

There are two different adjustments you could make. For your first edit,
start with **the map-opening adjustment** below. It changes the main window's
initial view while leaving Fit/Reset and object focusing available as they are.

The existing call chain is:

```text
MainWindow._select_level()       src/ui/main_window.py
  → Viewport.set_model()         src/renderer/viewport.py
    → Viewport.reset_camera()
      → Camera.fit_bounds()     src/renderer/camera.py
```

`fit_bounds()` centers the camera target on the model's bounding box and
calculates a sphere around the box using half its diagonal. It places the
camera far enough away to fit that sphere at the current viewport aspect
ratio, then adds a margin. That conservative full-scene framing can leave
considerable empty space around a wide, relatively flat track.

### A. Change the main map's opening distance

Open `src/ui/main_window.py` and search for `def _select_level(`. Inside that
method, find these two lines:

```python
        self.viewport.set_model(self.current_model, self.current_textures)
        self.toolbar.set_segment_count(len(self.current_model.segments))
```

Replace those two lines with this block, keeping its indentation:

```python
        self.viewport.set_model(self.current_model, self.current_textures)
        camera = self.viewport.camera
        if camera.view == "Perspective":
            camera.position = camera.target + (
                camera.position - camera.target
            ) * 0.80
        self.viewport.update()
        self.toolbar.set_segment_count(len(self.current_model.segments))
```

The new position retains the direction from the map center to the camera,
but multiplies that distance by `0.80`:

| Multiplier | Opening distance compared with the current view |
|---|---|
| `1.00` | Same distance |
| `0.90` | 10% closer |
| `0.80` | 20% closer; a useful first experiment |
| `0.65` | 35% closer |
| `1.20` | 20% farther away |

This runs when the main window selects/reloads a level. It works for stock
maps and imported geometry shown by that selection path. It does not change
the separate Course Builder/model/import-preview cameras, the movement speed,
or game data. Top/Front/Right views are left alone by the condition.

Save the file, restart, and select a few maps. **F still returns to the original
whole-map fit**, and double-clicking an object still uses the existing focus
distance. A closer opening view naturally shows less of the map at once.
Keep **Preview saved camera FOV** disabled while comparing results, so the
level's saved game FOV does not replace the normal editor FOV during testing.

Undoing this source experiment means removing the added block and restoring
the original two lines. The editor's Ctrl+Z handles course edits, not edits
made to Python files in your code editor.

### B. Alternatively, change the shared Fit distance

If you want to change Fit/Reset, object focus and other windows that use the
shared camera fit, open `src/renderer/camera.py`, find `def fit_bounds(`, then:

```python
        distance = radius / math.sin(min(half_vertical, half_horizontal)) * 1.15
```

Changing the final `1.15` to `0.90` brings the fitted eye position about 22%
closer than it is now (`0.90 / 1.15`). Smaller values move closer; larger
values move farther away. This affects perspective framing. Orthographic
visible size is controlled separately by:

```python
        self.ortho_height = radius * 2.3 / min(max(aspect, .01), 1.)
```

Reducing `2.3` makes Top/Front/Right fits show a smaller area. Unlike option A,
these are shared behavior changes across callers, including object focus and
preview windows. Applying both A and B compounds their distance reductions.

The existing camera tests assert that a normal Fit contains all bounding-box
corners. A tighter shared Fit may violate that promise on some shapes or
window proportions. Option A preserves the shared Fit calculation and that
test expectation while giving you a closer initial main-map view.

## 4. Other camera settings and the places that override them

| Want to change | Look for | Important detail |
|---|---|---|
| Fit viewing angle | `Camera.fit_bounds()` in `renderer/camera.py` | It currently resets Perspective yaw/pitch/FOV to `-130.0, -25.0, 60.0`. More negative pitch looks farther downward. |
| Angle after changing projection | `Camera.set_view()` in the same file | This has its own Perspective/Top/Front/Right angle table. |
| Initial camera values | The `Camera` dataclass near the top of the same file | Fit and projection changes can overwrite these values. Changing just the dataclass FOV will not change the FOV reset performed by Fit. |
| Mouse-look sensitivity | `Camera.look()` | The `0.18` multipliers convert mouse motion into angle changes. |
| Wheel sensitivity | `Camera.zoom()` | Perspective uses FOV, currently 3 degrees per notch, limited to 20–100. Orthographic zoom multiplies the visible height by `0.85 ** steps`. |
| Normal movement speed | `Viewport.set_model()` / `set_camera_speed()` in `renderer/viewport.py` | Whole-scene radius sets the baseline, then the toolbar percentage scales it. The dataclass's `speed=25.0` gets replaced on scene load. |
| Shift boost | `Camera.move()` | The boost multiplier is currently `4.0`. |
| Mouse buttons and keyboard bindings | Mouse/key event methods in `renderer/viewport.py` | Camera math is in `camera.py`; Qt events decide when to call it. |

Perspective wheel zoom currently changes the lens's field of view rather
than moving the eye. The worked example moves the eye. Saved **Settings →
camera FOV** belongs to the game's level data; use the renderer files when
you want to change only how the editor starts or navigates.

## 5. Where to look for other changes

| Feature | Main files |
|---|---|
| Application startup, theme, text colors and widget styling | `src/main.py`: `configure_surface_format()`, `configure_theme()`, `main()` |
| Main menus, opening dialogs, status bar and coordination | `src/ui/main_window.py`: `MainWindow`, `_create_menus()`, `_update_edit_actions()` |
| Animated About dialog and its ROM artwork | `src/ui/about_window.py`; `src/core/about_artwork.py` loads and assembles the images. |
| Top toolbar controls and their text | `src/ui/toolbar.py`; signal connections live in `main_window.py` |
| Left-hand level list and filtering | `src/ui/level_panel.py` |
| Right-hand tabs and object properties | `src/ui/object_inspector.py`; decoded object schemas are in `src/core/objects.py` |
| Moving, selecting and drawing objects | `src/renderer/viewport.py`, `camera.py`, `gizmos.py`, `object_mesh.py` |
| Track/sprite rendering and alpha behavior | `src/renderer/track_mesh.py`, `shaders.py`, `transparency.py` |
| Fish, butterflies and projected artwork | `src/core/special_art.py`, `src/renderer/special_mesh.py` |
| Checkpoints, AI routes and course creation | `src/core/routes.py`, `course.py`; `src/ui/route_panel.py`, `course_builder.py` |
| Track materials, face UVs and geometry | `src/core/materials.py`, `geometry.py`; `src/ui/material_panel.py`, `geometry_panel.py` |
| Custom track import and textures | `src/core/track_import.py`, `track_segments.py`, `track_artwork.py`; `src/ui/track_import_dialog.py` |
| PNG/texture/sprite exchange | `src/core/textures.py`, `image_assets.py`; `src/ui/image_browser.py` |
| Shared object properties and models | `src/core/global_objects.py`, `model_editing.py`, `object_rebuild.py`; the matching UI files |
| Undo/redo, project saving and edited ROM export | `src/core/editing.py`; `src/core/export_report.py` supplies reports |
| Original ROM loading and compressed data | `src/core/rom.py`, `compression.py` |
| OBJ export | `src/core/exporter.py` |
| Version shown in the app | `src/__init__.py`; keep `pyproject.toml` consistent when making a release |

When you know a button's visible text, search that text across `src/` first.
When you know a method name, search for both its definition and calls to it.
The same renderer is reused by several windows, so callers tell you how wide
a change's effects will be. In an editor with folder search, scope the search
to `src` to avoid the large reference and generated-output folders.

## 6. How an edit reaches the screen and the ROM

An object property edit follows approximately this path:

```text
ObjectInspector emits edit_requested
  → MainWindow._apply_edit()
    → EditSession.set_position() / set_parameter() / another edit operation
      → validated project overlay and undo history change
    → MainWindow._refresh_edits()
      → panels and derived scene data refresh
      → Viewport redraws updated artwork, meshes, gizmos and routes
```

Use `EditSession` for edits that must survive project saving, undo/redo and
ROM export. The original ROM remains the base; the session records changes
on top of it. Directly changing a displayed vertex or widget can alter the
screen without recording the corresponding project/ROM edit.

Object identities also matter. Pass around the object's stable `obj.key`
instead of treating a list row as its identity: rows and serialized positions
can change after adding/deleting objects. Existing handlers show the intended
pattern for selection and refresh.

The renderer maintains derived CPU data and GPU buffers. Methods such as
`set_sprites()`, `refresh_materials()` and `refresh_geometry()` arrange the
appropriate refresh. Calling `update()` schedules a repaint, but does not
by itself rebuild a stale GPU buffer. Follow the existing refresh route for
the kind of data you changed. GPU creation/deletion belongs in the renderer's
existing OpenGL-context lifecycle.

Changes to view behavior, labels or theme usually need only the UI/renderer.
Adding a new saved game field also needs its core parser/writer, validation,
history/project support, export checks and UI refresh. Existing nearby fields
are useful examples. Trace game field definitions and readers in the local
`research/Diddy-Kong-Racing/include/` and `src/` before assigning meanings or
changing binary layouts; preserve bytes you do not deliberately support.

## 7. Checking your edits and finding errors

Start with a small change, save, restart, and check the actual control you
changed. For the map-opening camera example, compare Ancient Lake and Central
Area, switch levels, press F, focus an object and try Top view. Those actions
confirm whether you changed only the opening distance or a shared fit path.

Run the relevant camera tests from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_camera.py tests/test_camera_pan.py --basetemp=artifacts/pytest-my-camera
```

Use a temporary directory reserved for pytest; pytest may clear its own base
temporary directory on a later run. Run suites sequentially when they use the
same directory. Other useful groups are:

| What you changed | Relevant existing tests |
|---|---|
| Object parameters, positions or structural edits | `test_objects.py`, `test_editing.py`, `test_object_structure.py` |
| Sprite orientation, alpha picking or rendering state | `test_sprite_billboards.py`, `test_sprites.py`, `test_rendering_edit_context.py` |
| Checkpoints and course building | `test_routes_research.py`, `test_course.py`, `test_course_refresh.py` |
| Track geometry/import | `test_geometry.py`, `test_track_import.py`, `test_track_segments.py` |
| PNG artwork | `test_textures.py`, `test_image_assets.py`, `test_track_artwork.py` |
| Shared model editing | `test_model_editing.py`, `test_object_rebuild.py` |

All those files are inside `tests/`. For broader core changes, the full suite is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=artifacts/pytest-my-full
```

The full suite takes several minutes on this machine. Automated tests check
math, formats and edit/export behavior; visually inspect rendering changes
in the editor too. Editor-only camera changes require no new ROM export.
Gameplay data changes still need your normal in-game test of an exported ROM.

Launching from PowerShell leaves Python tracebacks visible. Read the final
error message, then look for the last stack entry inside `src/`: it identifies
the application file and line that raised the error. A syntax/indentation
error after a small edit often means a missing colon/bracket or mismatched
spaces. An import error often means the wrong interpreter or working folder.

For a quick syntax check of one edited file without launching the application:

```powershell
.\.venv\Scripts\python.exe -c "import ast; from pathlib import Path; ast.parse(Path('src/ui/main_window.py').read_text(encoding='utf-8-sig')); print('Syntax OK')"
```

A syntax check does not test runtime behavior. If the editor starts but a
change seems absent, confirm that you saved the file, restarted the right
process, launched from this project folder, and edited the method that actually
runs. Camera defaults are a good example: `fit_bounds()` can overwrite an
earlier dataclass setting, and a repaint can keep an old mesh until its refresh
path runs.

## 8. Keeping useful notes

`STATUS.md` records the current milestone. `docs/ROADMAP.md` records feature
scope and deferred work. Feature-specific guides document the existing formats
and workflows. For your own experiments, record the file/method, old value,
new value and what you observed; that makes it easy to keep or reverse a change.

Start with the map-opening distance example, then labels/theme and small
camera preferences. Once the UI → session → refresh flow is familiar, larger
editing features are easier to extend without losing undo or saved changes.

## Working grid and parameter labels

`src/renderer/work_grid.py` builds world-aligned editing planes and the corner
orientation widget. `Viewport._draw_grid` chooses spacing from the camera zoom;
`reset_grid_plane` chooses the initial course work height. `src/ui/toolbar.py`
creates the Grid menu, and `MainWindow` synchronizes its checked states.
The grid is a display aid; it does not translate the track or change snap origins.

`src/core/parameter_labels.py` centralizes verified display names, unit hints and
choice lists. Add labels there after checking the local game's readers. Keep
`ENTRY_LAYOUTS` field keys and offsets unchanged when only renaming a displayed
field. The Objects inspector and Cinematics panel share this metadata. See
[Verified parameter labels](PARAMETER_LABELS.md) for the current mapping.

## Material picker and preview lifetime

`src/ui/material_panel.py` owns batch selection and the current material card.
`src/ui/material_picker.py` provides the visual course-material and shared-ROM
texture dialogs. Their validated drafts emit viewport-only models; the main
window keeps its committed model separate. Apply closes the preview before
sending one existing material edit transaction. Context changes and undo/redo cancel the draft; save retains it outside
the committed project. `texture_assignment_error` prefilters incompatible rendering
passes; the existing full writer remains the final validator.
