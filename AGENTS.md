# AGENTS.md — Diddy Kong Racing (N64) Level & Track Viewer

## Local Git and selected next scope (2026-10-30)

This folder tracks the history of https://github.com/kraekin/DKR-Workshop.
Work and commits stay local. The user performs remote pushes; do not push or
otherwise publish repository changes without explicit later authorization.
Preserve local ROMs, research/build directories, personal test assets and running
editors. Keep proprietary assets excluded from commits.

The selected creator-workflow scope is a visual improvement to the existing
Add Objects catalog, followed by complete object artwork export. Favorites,
presets and reusable groups are excluded. Finish local Git setup first; do not
fold other audit suggestions into this scope.

## 1. Project Overview
This project is a desktop 3D Level and Track Viewer (with `.obj` export capabilities) for the Nintendo 64 game **Diddy Kong Racing (DKR)**, written in Python using **PySide6** for the GUI and an OpenGL viewport (`QOpenGLWidget`) for 3D rendering.

## 2. Authoritative Local Reference (DO NOT FETCH FROM GITHUB)
You have direct local access to the matching Diddy Kong Racing N64 decompilation repository on disk. **Never guess binary offsets, compression headers, or struct layouts.** Always inspect the local decompilation files first:

* **Local Decomp Path:** `D:\RomHacking\n64\dkr\research\Diddy-Kong-Racing`

When implementing parsers, inspect the following paths inside that directory:
* `include/` and `src/` — Authoritative C struct definitions (`include/structs.h`, `src/tracks.c`, `src/game.c`, `src/objects.c`, `src/textures_sprites.c`, `src/asset_loading.c`, `src/gzip.c`, and `include/f3ddkr.h`).
* `tools/dkr_assets_tool_extract.json` and `ver/splat/` — Authoritative asset section order, SHA-1 identities and ROM offsets. This checkout has no generated `assets/`, `extract-ver/`, or linker scripts yet. USA 1.0 is `us.v77`; the target Rev 1 / USA 1.1 is `us.v80` (SHA-1 `6d96743d46f8c0cd0edb0ec5600b003c89b93755`). Read generated assets only if they exist.
* `tools/` — Extraction and compression utilities used by the decomp build system (e.g., Rare gzip / `dkr_assets_tool`).

---

## 3. Session Tracking & Workflow Rules
1. **Maintain `STATUS.md`:** Before starting a task and after completing any milestone, read and update `STATUS.md` in the project root. Log completed features, verified binary struct formats, and the exact next step to prevent context drift.
2. **Clean Directory Structure (NO Aliasing):** Put all application code inside a single `src/` directory. **Do NOT** create a duplicate `dkr_viewer/` package directory alongside `src/` or set up module aliases.
3. **Clean-Room Asset Policy:** Never hardcode extracted proprietary binaries into git. The viewer must either load a user-selected `.z64` ROM (or byte-swapped `.v64`/`.n64` converted in-memory to Big-Endian) OR read extracted binary/JSON assets directly from `D:\RomHacking\n64\dkr\research\Diddy-Kong-Racing`.
4. **User Testing Preference:** The user performs in-game testing. Do not generate sample/test ROMs for them or launch emulator playtests. Continue automated headless/native checks; use in-memory export validation or temporary test files where required, and keep gameplay confirmation separate. Preserve existing unsaved editor processes.

---

## 4. Tech Stack & Dependencies
* **Language:** Python 3.11+ (strictly type-annotated)
* **GUI Framework:** `PySide6` (Qt6) — `QMainWindow`, `QDockWidget`, `QTreeWidget`, `QOpenGLWidget`
* **3D Rendering:** `PyOpenGL` (or `moderngl`) inside `QOpenGLWidget` (OpenGL 3.3 Core Profile)
* **Math & Binary Parsing:** `numpy` (fast vertex/triangle buffer processing), Python `struct` and `dataclasses`, `zlib` (for DKR Rare gzip: LE u32 size + 09 + raw DEFLATE), `zstandard` (bounded read-only BizHawk state inspection)
* **Texture Decoding:** `Pillow` + `numpy` (decoding N64 RGBA16, RGBA32, CI4, CI8, IA4, IA8, IA16, I4, I8 to RGBA8888)
* **Testing:** `pytest` (all binary parsers must have headless unit tests)

---

## 5. Required Directory Layout
Strictly adhere to this flat `src/` layout:

```text
dkr-track-viewer/
├── AGENTS.md
├── STATUS.md
├── pyproject.toml
├── README.md
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point, QSurfaceFormat (GL 3.3 Core), QApplication
│   ├── core/                   # Pure Python + NumPy (NO PySide6 or OpenGL imports allowed)
│   │   ├── __init__.py
│   │   ├── rom.py              # .z64/.v64 endian handling, master asset table lookup
│   │   ├── compression.py      # DKR Rare gzip (LE u32 size + 09 + raw deflate)
│   │   ├── level_header.py     # LevelHeader struct parser (geometry ID, object map ID, skybox, fog)
│   │   ├── level_model.py      # LevelModel, BSP segments, Vertex (10-byte XYZ+RGBA), Triangle, Batch
│   │   ├── materials.py        # Protected existing model material fields and track-face picking
│   │   ├── geometry.py         # Fixed-topology linked XYZ, stock spatial/collision envelope and runtime bounds
│   │   ├── track_rebuild.py    # Phase23A typed stock reconstruction, runtime checks and explicit stock ROM export
│   │   ├── track_import.py     # Phase23B bounded OBJ/compiler, collision neighbors, static one-segment layout
│   │   ├── track_segments.py   # Phase23C spatial clipping/BSP/PVS, protected seam guides, local query proof and v10 validation
│   │   ├── track_artwork.py    # Phase24 MTL/PNG staging, canonical dedicated textures and TMEM bounds
│   │   ├── minimap.py          # Protected minimap fields, sprite refs and HUD projection
│   │   ├── image_assets.py     # Fixed-layout encoders, PNG exchange and sprite anchors
│   │   ├── image_usage.py      # Known texture/sprite dependencies and shared levels
│   │   ├── objects.py          # Level Object Map parser (spawns, checkpoints, balloons, zippers)
│   │   ├── object_models.py    # Physical meshes, vertex clips and controller targets
│   │   ├── model_editing.py    # Phase28 protected mesh/clip writers, exchange, uses and plans
│   │   ├── object_rebuild.py   # Phase29 canonical static topology/material/reference compiler and source RAM reports
│   │   ├── special_art.py      # Source-built animals, portraits and projected zippers
│   │   ├── environment.py      # Saved fog, texture timing/scroll and transient waves
│   │   ├── cinematics.py       # Existing actor/camera tracks and deterministic NTSC sampling
│   │   ├── structure.py        # Read-only resource audit and isolated structural research drafts
│   │   ├── object_structure.py # All-type templates, stable editor identities, structural bounds and v7 rows
│   │   ├── runtime_audit.py    # Read-only Rev1 RDRAM/BizHawk state measurements
│   │   ├── bush_experiment.py  # Restricted user-run Phase20 one-bush research preview/export
│   │   ├── bizhawk_capture.lua # Optional user-run read-only RDRAM capture
│   │   ├── editing.py          # Object/group edit history, project overlays and ROM export
│   │   ├── placement.py        # Verified transforms, grouped patches and terrain queries
│   │   ├── routes.py           # Existing lane/connection edits and graph diagnostics
│   │   ├── course.py           # Phase25 staged checkpoint/grid plans, source bounds, diagnostics and preflight
│   │   ├── course_names.py     # Phase26A lossless name records, Latin font metrics, plans and section24/25 rebuild
│   │   ├── global_objects.py   # Phase27 protected shared headers, typed artwork compatibility, dependencies and staged plans
│   │   ├── research.py         # Field evidence, project-only notes and comparisons
│   │   ├── export_report.py    # Read-only exact export budgets, dependencies and diffs
│   │   ├── level_settings.py   # Verified fixed header fields, references and validation
│   │   ├── textures.py         # N64 textures, sprite definitions, anchors and world instances
│   │   └── exporter.py         # Wavefront .obj + .mtl + PNG texture exporter
│   ├── renderer/               # OpenGL 3.3 Core rendering engine
│   │   ├── __init__.py
│   │   ├── viewport.py         # QOpenGLWidget subclass, mouse/WASD input loop
│   │   ├── camera.py           # 3D Fly-camera (WASD + Right-Click look) & Orbit camera math
│   │   ├── shaders.py          # GLSL shaders for vertex colors + N64 textures + alpha discard
│   │   ├── track_mesh.py       # VAO/VBO management for track batches & wireframe overlay
│   │   ├── object_mesh.py      # Shared model GPU buffers and clip pose updates
│   │   ├── transparency.py     # Shared camera-depth order for blended scene ranges
│   │   ├── special_mesh.py     # Persistent buffers/textures for special artwork
│   │   ├── environment.py      # Shared fog UBO, sky/backdrop and dynamic surfaces
│   │   └── gizmos.py           # 3D markers/spheres/lines for objects and AI raceline waypoints
│   └── ui/                     # PySide6 GUI widgets
│       ├── __init__.py
│       ├── main_window.py      # Main window, menu bar (Open ROM, Load Decomp Dir, Export .OBJ)
│       ├── level_panel.py      # Left dock: filterable list of all DKR tracks, hubs, and bosses
│       ├── object_inspector.py # Right dock: property viewer for clicked/selected level objects
│       ├── object_palette.py   # Full304-ID add dialog, provenance, target map and XYZ
│       ├── export_report.py    # Read-only/copyable ROM preflight report dialog
│       ├── placement_panel.py  # Existing-object group/snap/align controls
│       ├── route_panel.py      # Existing checkpoint lanes and directed AI connections
│       ├── course_builder.py   # Phase25 independent mouse-placement/route/grid preview and atomic Apply
│       ├── course_names.py     # Phase26A dedicated Edit-menu window, multi-course drafts and atomic Apply
│       ├── global_objects.py   # Phase27 separate Edit-menu window, shared-property/artwork drafts and affected levels
│       ├── model_editor.py     # Phase28 separate model/clip playback, tables, exchange and staged Apply
│       ├── research_panel.py   # Retired UI retained internally for project-note compatibility
│       ├── material_panel.py   # Track textures/surfaces, batches, face UVs and vertex colors
│       ├── geometry_panel.py   # Existing vertex/face selection, XYZ and linked geometry controls
│       ├── track_rebuild_dialog.py # Cancellable stock rebuild checks and user-triggered stock export
│       ├── track_import_dialog.py # Independent staged GL preview, material mapping and atomic Apply
│       ├── minimap_panel.py    # Existing map settings and sprite/marker alignment preview
│       ├── cinematic_panel.py  # Existing path nodes, timing/events, edits and camera preview
│       ├── image_browser.py    # Image thumbnails, PNG export/staged import, anchors/timing
│       └── toolbar.py          # Toggles: Wireframe, Vertex Colors, Textures, Objects, Racelines
└── tests/
    ├── test_camera.py          # Phase 1 headless camera invariants
    ├── test_rom_and_compression.py # Phase 2 parser checks
    ├── test_level_model.py
    ├── test_materials.py        # Phase 14 material protection, projects, growth and OBJ
    ├── test_geometry.py         # Phase22 seam/BSP/collision math, protected XYZ, picking, v8 and export
    ├── test_track_rebuild.py    # Phase23A all55 stock records, runtime branches, compression and ROM isolation
    ├── test_track_import.py     # Phase23B OBJ, new collision/layout, v9 history/projects and in-memory exports
    ├── test_track_segments.py   # Phase23C all55 templates, source queries/seam planes, v10 and helper-free OBJ export
    ├── test_track_artwork.py    # Phase24 conversion, sidecars, appended IDs, atomic history/v11 and untouched ROM assets
    ├── test_minimap.py          # Phase 15 fields, projection, projects and in-memory export
    ├── test_image_assets.py     # Phase 16 encoders, PNG workflow, asset history and export
    ├── test_textures.py
    ├── test_objects.py
    ├── test_editing.py
    ├── test_export_report.py    # Phase 10 budget/diff/migration checks
    ├── test_level_settings.py   # Phase 11 field/reference/project/ROM checks
    ├── test_placement.py        # Phase 12 grouped transforms and surface math
    ├── test_routes_research.py  # Phase 13 route bytes, diagnostics, notes/migration
    ├── test_course.py           # Phase25 route/grid math, identities, refusals, projects and ROM isolation
    ├── test_course_names.py     # Phase26A all65 names, fonts, language retention, v12/history and ROM isolation
    ├── test_global_objects.py   # Phase27 all304 headers, protected bytes/references, dependency/history/v13 and ROM isolation
    ├── test_model_editing.py    # Phase28 model/clip identity, signed deltas, protection, v14/history and ROM isolation
    ├── test_object_rebuild.py   # Phase29 all207 static schemas, user extrusion, protected arrays, v15 and ROM isolation
    ├── test_sprites.py
    ├── test_special_art.py      # Phase 17 decals, procedural poses and overlay refresh
    ├── test_environment.py      # Phase 18 defaults, frame modes, scrolling and water
    ├── test_cinematics.py       # Phase 19 ordering/timing/loops, camera, projects and export
    ├── test_cinematic_refresh.py # UI cache owners through structural changes; no QApplication/GL
    ├── test_structure.py        # Phase 20 stable identities/history, map bounds and research round trips
    ├── test_object_structure.py # Phase21 all304 types, stable IDs, v7 projects, graph warnings and export
    ├── test_inplace_inflate.py  # Source-model map inflater, unsafe overlap and malformed streams
    ├── test_runtime_audit.py    # Bounded RAM/state readers, byte orders, allocator/counter checks
    ├── test_bush_experiment.py  # One-clone profile, residency/refusals, reload and no-overwrite publication
    ├── test_capture_helper.py   # Standalone Lua with stub APIs; no emulator execution
    └── test_mouse_move.py
```

---

## 6. DKR Binary Format Reference Rules
Always cross-check these specifics against `D:\RomHacking\n64\dkr\research\Diddy-Kong-Racing\include` and `src\`:

1. **Endianness:** N64 structs and asset tables are **Big-Endian (`>`)**. The DKR Rare gzip uncompressed-size prefix is explicitly **Little-Endian (`<I`)**.
2. **Rare Gzip Compression:** DKR uses a **5-byte** header: LE u32 uncompressed length, byte `0x09`, then raw DEFLATE (`zlib.decompress(data[5:], -15)`). These streams have no `0x1172` magic. Verify per-section wrapping: compressed textures have an outer 0x20-byte TextureHeader before this stream; model/object-map entries start with it directly. See `src/gzip.c` and `tools/dkr_assets_tool_src/libs/gzip/DKRCompression.cpp`.
3. **DKR `F3DDKR` Vertices & Triangles:**
   * Unlike standard SM64 (`F3D`), DKR uses custom `F3DDKR` microcode where vertices are **10 bytes** (`>hhhBBBB` — `s16 x, y, z` and `u8 r, g, b, a`).
   * Triangles are **16 bytes** (`>BBBBhhhhhh` — `u8 flags, vi0, vi1, vi2`, `s16 uv0_u, uv0_v, uv1_u, uv1_v, uv2_u, uv2_v` in `s10.5` fixed-point format). All six UV components are signed. Definitions are in `include/structs.h`; commands are in `include/f3ddkr.h`.
4. **Segmented Level Models:** DKR tracks are divided into visibility segments (`LevelModelSegment`) with bounding boxes and triangle batch lists (`BatchInfo`). Each batch specifies a texture index, vertex offset, and triangle offset.

---

## 7. Incremental Implementation Roadmap & Phase Gates

CRITICAL AGENT RULE: Execute this roadmap strictly one phase at a time. Do NOT jump ahead to later phases until the current phase's Verification Gate passes and STATUS.md is updated with the verified findings (struct sizes, asset table offsets, and test results). Ensure STATUS.md ONLY tracks the current milestone, it should remain compact and only provide the status of the current feature/milestone being implemented. 

**Phase 0: Decompilation Recon & Spec Verification (Read-Only)**
Before writing any parser code, inspect D:\RomHacking\n64\dkr\research\Diddy-Kong-Racing to document the exact binary layouts in STATUS.md.
1. Locate Asset Definitions: Inspect `tools/dkr_assets_tool_extract.json`, `ver/splat/dkr.us.v80.yaml` and `ver/symbols/undefined_syms.txt` for the Rev 1 master LUT at `0xED0E0`, asset base `0xED1B0`, section order and identities. Requested data sections are TEXTURES_3D=2, LEVEL_OBJECT_MAPS=21, LEVEL_HEADERS=23, LEVEL_NAMES=25, LEVEL_MODELS=27, and object headers `ASSET_OBJECTS`=34 (its table is `ASSET_OBJECT_HEADERS_TABLE`=33). Do not substitute the USA 1.0 LUT at `0xECB60`.
2. Verify Core C Structs: Read `include/structs.h`, `include/level_object_entries.h`, `src/tracks.c`, `src/game.c`, `src/objects.c`, `src/textures_sprites.h`, and `include/f3ddkr.h`. Verified sizes: LevelHeader C=0xC4 / serialized record=0xC8 (tool adds u32 tail); LevelModel=0x4C; LevelModelSegment=0x44; TriangleBatchInfo=12; Vertex=10 (`>hhhBBBB`); Triangle=16 (`>BBBBhhhhhh`); TextureHeader=0x20. Preserve unknown fields and distinguish ROM values from runtime pointers.
3. Phase 0 Verification Gate: Create STATUS.md and document the exact ROM offsets, table indices, and C struct byte sizes discovered in the local decomp repo.

**Phase 1: Project Scaffold, PySide6 Shell & 3D OpenGL Viewport**
Build the GUI application shell and interactive 3D camera before touching any binary game data.
1. Project Setup: Create pyproject.toml with dependencies (PySide6, PyOpenGL, numpy, Pillow, pytest). Enforce the single src/ layout (src/main.py, src/core/, src/renderer/, src/ui/).
2. OpenGL 3.3 Core Viewport (src/renderer/viewport.py & camera.py): Configure QSurfaceFormat for OpenGL 3.3 Core Profile with 24-bit depth buffer and 4x MSAA in src/main.py. Implement a 60 FPS fly-camera (WASD movement, Q/E vertical, Shift speed boost, Right-Mouse-Button look, Scroll-Wheel zoom) plus a "Reset / Fit to Bounds" shortcut (F key). Render a 3D reference ground grid (XZ plane) and RGB origin axis lines (X=Red, Y=Green, Z=Blue).
3. Main Window Shell (src/ui/main_window.py): Create QMainWindow with menu actions (Open ROM, Set Decomp Directory, Export Wavefront .OBJ), a left LevelPanel dock, a right ObjectInspector dock, a top render toggle toolbar, and a QStatusBar.
4. Phase 1 Verification Gate: Run "python -m src.main" and verify the window opens without OpenGL errors and the 3D grid can be orbited/flown around smoothly. Update STATUS.md.

**Phase 2: ROM Loader, Rare Gzip Decompression & Master Asset Table**
Implement the core binary I/O layer to read either a raw DKR ROM or extracted decomp assets.
1. ROM Endianness & Asset LUT (src/core/rom.py): Support .z64 (Big-Endian 0x80371240), .v64 (byte-swapped 0x37804012), and .n64 (little-endian 0x40123780), normalizing to Big-Endian bytes in memory on load. Parse the Master Asset Table (__ASSETS_LUT_START) to resolve asset table slices by AssetType enum.
2. Rare Gzip Decompressor (src/core/compression.py): Follow `src/gzip.c`: LE u32 uncompressed size + byte 09, then raw DEFLATE at +5. Validate output length; permit entry alignment padding. Duplicate table offsets are vacant entries (Rev 1 object-map slots 81 and 99); return empty bytes for them without inflation, matching src/objects.c:992. Support compressed and uncompressed entries by the section's documented semantics, not guessed magic. Textures add an outer 0x20-byte header before compressed streams.
3. Level Header & Name Table (src/core/level_header.py): Use table spans (Rev 1 serialized header 0xC8, C struct 0xC4); geometry=0x34, collectables object map=0x36, skybox=0x38, secondary object map=0xBA. The ROM AI tables at 0x20 are inline bytes, not a pointer. Parse ASSET_LEVEL_NAMES and ASSET_LEVEL_HEADERS so every track, hub world, boss arena, and cutscene stage shows its human-readable name, geometry_id (LevelModel index), object_map_id, skybox ID, and fog/background color settings. Wire this list into src/ui/level_panel.py with a search filter bar.
4. Phase 2 Verification Gate: Write tests/test_rom_and_compression.py testing asset table indexing, Rare gzip decompression, and LevelHeader unpacking against data in D:\RomHacking\n64\dkr\research\Diddy-Kong-Racing. Run "pytest -v" — all tests must pass before proceeding to Phase 3.

**Phase 3: Untextured 3D Track Geometry & Wavefront .OBJ Export**
Parse the LevelModel binary format and get the full 3D track geometry on screen and exportable.
1. LevelModel & BSP Segment Parser (src/core/level_model.py): Cross-check include/structs.h and src/tracks.c in the decomp repo for pointer/offset fixups inside LevelModel. Parse the model header (numberOfSegments, numberOfTextures, bounding box, segment array). For each LevelModelSegment, unpack: Vertex array (10 bytes per vertex: Big-Endian hhhBBBB for s16 x, y, z and u8 r, g, b, a), Triangle array (16 bytes per triangle: Big-Endian BBBBhhhhhh for u8 flags, vi0, vi1, vi2 and s16 uv0_u, uv0_v, uv1_u, uv1_v, uv2_u, uv2_v), and TriangleBatchInfo array (batch texture index, vertex offset, triangle offset, and render flags). Read numberOfBatches + 1 records: the last is a terminal record whose vertex/face offsets delimit the final batch; its other fields may be garbage. BSP has numberOfSegments - 1 internal nodes with -1 children denoting leaves. Convert batch-local vertex indices (batch.verticesOffset + tri.vi0, etc.) into flat, validated numpy vertex and index buffers; validate against the loaded batch vertex range as well as segment bounds.
2. Vertex-Colored OpenGL Renderer (src/renderer/track_mesh.py & shaders.py): Upload the parsed track segments into OpenGL VAOs/VBOs. Skip batch RENDER_HIDDEN flag 0x100 as src/tracks.c does. Preserve raw colors, but apply the loader fixup for vertices with R=G=1: display RGB=(128,128,128), alpha=stored B. Write a GLSL shader that renders vertex colors (v_color) with optional backface culling (BACKFACE_DRAW triangle flag 0x40 disables culling for double-sided geometry). Add toolbar toggles for: Solid Vertex Colors, Wireframe Overlay, Segment Bounding Boxes, and Isolate Selected Segment. Auto-fit the camera position to the track's bounding box when a level is selected in level_panel.py.
3. Untextured .OBJ Exporter (src/core/exporter.py): Implement Wavefront .obj export writing all segments as named groups (g segment_0, g segment_1...) with "v x y z r g b" vertex lines (normalized loader-corrected RGB) and one-based "f" face definitions. Preserve original XYZ/winding and include all batches, including hidden geometry, regardless of viewport isolation.
4. Phase 3 Verification Gate: Write tests/test_level_model.py asserting that loading a known track (e.g., Ancient Lake or Timber's Island hub) produces valid segment counts, zero out-of-bounds vertex indices, and a valid .obj output file. Run "pytest -v" and visually verify track geometry in the viewport.

**Phase 4: N64 Texture Decoding, UV Mapping & .MTL Export**
Bring the tracks to life with full N64 textures, transparency, and material exports.
1. N64 Texture Decoder (src/core/textures.py): Reference include/structs.h, src/textures_sprites.c and src/textures_sprites.h in the local decomp. Disk frame count is byte 0x12 (runtime u16 >> 8); line-swap flag is 0x400, not the stale 0x04 struct comment. Clamp U/V flags are 0x40/0x80; material_init also clamps non-power-of-two dimensions. Compressed assets have an outer 0x20-byte header plus a Rare stream containing complete frame headers/pixels; frameSize at 0x16 advances to the next frame. Undo flagged odd-row swaps in pairs of 4-byte blocks, or 8-byte blocks for RGBA32, matching imageHelper.cpp:191. The runtime uses pre-swapped load macros rather than modifying pixels in RAM. CI palettes are read from section 14 (32 bytes CI4; 128 bytes CI8 in this loader); that section is empty in original Rev 1, so test CI using synthetic palettes. Implement RGBA16, RGBA32, CI4/CI8, IA16/IA8/IA4 and I8/I4 into uint8 RGBA8888 arrays and PIL.Image objects. Extracted Texture JSON points to decoded PNGs; reverse the extractor's optional flipped-image transformation when loading them.
2. DKR Fixed-Point UV Scaling & Wrap Modes: Convert signed UVs using uv / (32 * bound frame dimensions), preserving coordinates outside [0,1]. GL uploads N64 rows unchanged and uses raw V; OBJ uses 1-V against top-to-bottom PNGs. Preserve per-corner UV seams. Apply texture header clamp/wrap rules (no local evidence for mirror). Batch texOffset selects a static frame as texOffset >> 2 when texOffset < frameCount * 4, else frame 0 (tracks.c:1953, material_set:704). Render texture * vertex color, alpha discard below 0.1, loader-corrected vertex alpha, cutouts and semi-transparent batches. This phase covers scenery baked into LevelModel; object-map gizmos are Phase 5, and actual billboard artwork is Phase 6.
3. Full Textured .OBJ + .MTL Export (src/core/exporter.py): Upgrade the .obj exporter to write "vt u v" texture coordinates, generate a companion .mtl file with map_Kd material entries per texture ID, and dump all used track textures as .png files alongside the .obj.
4. Phase 4 Verification Gate: Write tests/test_textures.py testing every N64 texture format decoder and UV normalization. Verify in the GUI that toggling Textured Mode renders trees, roads, water, and signs with proper UV alignment and alpha cutouts.

**Phase 5: Level Object Maps, AI Racelines & Interactive Picking**
Parse the level's gameplay entities and render interactive 3D gizmos in the viewport.
1. Level Object Map Parser (src/core/objects.py): Inspect src/objects.c, include/structs.h and include/level_object_entries.h in the local decomp. Header is 16 bytes; BE u32 at0 counts entry payload bytes EXCLUDING this header, followed by 12 reserved bytes; inflated files can end with 0..7 zero alignment bytes. Common entry is 8 bytes (>BBhhh): byte0 is ID low8, byte1 bit7 is ID bit8, byte1 & 0x3F is runtime length, then s16 XYZ. All 9426 original Rev 1 entries leave bit6 clear, so the tool's 0x7F mask agrees; preserve bit6 separately. Translation section35 is 512 BE s16 values (512 = unmapped), pointing into 304 ASSET_OBJECTS headers. ObjectHeader fixed part is 0x78: signed behaviorId at0x54 and ASCII internalName[16] at0x60. Use the verified 128 behavior/entry schemas; retain all raw bytes and parameters. Read both level maps, deduplicating identical map IDs. Extracted maps use JSON objects -> glTF with per-node extras; their original raw bytes/alias IDs are not retained and must not be fabricated.
2. 3D Object Gizmos & AI Path Splines (src/renderer/gizmos.py): Render color-coded sphere/box/arrow markers for spawns, checkpoints, weapon balloons, bananas, zippers, scenery and sound triggers. Checkpoint entries are 0x1C: index9, angleYA, lateral AI offsets B..E, vertical offsets F..12, lane behavior selectors13..16 (not bit flags), isAltCheckpoint17, HUD course cue19, vehicleType1A. Bytes18/1B have no identified reader in Rev1; retain them. Detailed field meanings and behavior-code limitations are in docs/CHECKPOINT_FIELDS.md. vehicleType selects a checkpoint SET; LevelHeader s8[3] at0x4F maps Car/Hovercraft/Plane to those sets (game.c:492-497). Four AI lanes are separate from vehicle IDs (racer.c:9060-9064). Connect sorted main checkpoints as closed Catmull-Rom splines using objects.c:9642 coefficients, and substitute alternate checkpoints at matching indexes. AiNode entries are 16 bytes: nodeID9, adjacent[4]A..D, elevationE; draw explicit directed adjacency edges, not invented sequential loops. Marker/raceline overlays can remain visible through track surfaces for inspection.
3. Viewport Picking & Object Inspector (src/ui/object_inspector.py): Implement ray-sphere / ray-box intersection (or color-buffer picking) when left-clicking in the 3D viewport. Populate the right-hand ObjectInspector dock with the selected object's ID, internal name, world (X, Y, Z) coordinates, byte size, and raw parameter hex/int fields. Clicking an object in the ObjectInspector tree list should highlight it and focus the 3D camera on it on double-click.
4. Phase 5 Verification Gate: Write tests/test_objects.py verifying that parsing a level's object map reads the exact byte length without buffer overruns and resolves valid object IDs. Run full pytest suite and update STATUS.md as v1.0 Complete.

**Phase 6: ROM Sprite Scenery (user-requested extension after Phase 5)**
1. Inspect include/structs.h, textures_sprites.c:950-1047/1306, camera.c:1057 and object_functions.c before parsing. SPRITES data/table are sections12/13; TEXTURES_2D data/table are4/5. Serialized SpriteHeader is12 bytes followed by frame_count+1 u8 tile offsets; each frame uses consecutive 2D textures. Read signed TextureHeader posX/posY and signed sprite anchors; reproduce sprite_init_frame's pixel extents.
2. Resolve ObjectHeader modelType=1, model-relative modelIds array at0x10, signed model count at0x55, and entry modelIndex/balloonType with runtime fallback0. Apply verified per-behavior scale rules. Render direct physical scenery/collectable sprites as camera-facing quads with depth and alpha cutouts. Keep logic-helper icons as gizmos. Add an independent Sprites toggle; gizmo filters must not hide artwork. This milestone uses static first frames; animated spawners and 3D object models remain outside its scope.
3. Verification Gate: Headless malformed/synthetic/extracted-source tests, decode all193 sprite definitions and916 2D textures, resolve all65 levels, then real OpenGL level switching, billboard rotation, alpha/depth and existing-control checks. Update compact STATUS.md and detailed format notes. Stop for review after this extension.

**Phase 7: Basic Object Editing and Unknown-Byte Experiments (user requested)**
1. Add a headless edit session keyed by map ID/entry index, preserving raw entries, original IDs, lengths, reserved bytes and map alignment. Support signed16 XYZ, existing typed fields and all parameter bytes at offsets8 onward (including unknown/padding bytes). Keep the ID/size prefix protected; validate byte/type bounds without inventing meanings for unknown fields. Add undo/redo, dirty state and a versioned project overlay tied to the original Rev1 SHA-1.
2. Add editable inspector values, raw hex byte values, coordinate/nudge controls and live refresh of selected objects, sprites, gizmos and racelines. Preserve camera, selection and filters through edits. Runtime effects not represented by the viewer are tested by the user in-game.
3. Save projects and export a new BE ROM through Save As ROM. Recompress only changed object maps with the verified Rare wrapper, rebuild subtable/master offsets when needed, preserve every untouched section byte-for-byte and validate/recompute N64 checksums using local tools/n64crc.c. Never overwrite the loaded base ROM. Preserve the stock-ROM identity check; projects load the verified base plus their overlay.
4. Verification Gate: Headless edit/undo/project round trips, signed/byte bounds, malformed projects, no-edit ROM identity, exported map reload and untouched-asset byte comparisons. Real Qt edit/save/undo and RTX live-preview checks plus full pytest. Update STATUS.md and stop for review. Emulator/gameplay behavior is not claimed without running the game.

---

**Phase 8: Mouse Object Translation (user requested)**
1. Add headless projection/ray-plane drag math and reversible move previews. World-axis handles constrain one coordinate; center dragging follows the camera plane. Round to signed16 coordinates, support Ctrl snapping to the existing movement step, and commit one undo record on release. Cancel on Escape/focus loss without changing prior history or other bytes.
2. Render RGB X/Y/Z handles on the selected object, with consistent screen size and hit targets. Add a mouse-move toggle and live inspector/sprite/gizmo/raceline updates. Keep right-mouse camera controls available outside an active drag. Save/source/history operations must resolve the active gesture safely.
3. Verification Gate: Headless projection/drag/transaction tests, degenerate-angle/bounds/no-op cases, real Qt mouse drag/release/cancel/focus tests, single-step undo/redo and project/ROM round trips. Run full pytest and GPU regression checks, update STATUS.md and stop for review.
4. User-requested follow-up: camera framing must preserve movement speed through object selection/focus/deselection and segment fitting. Add a visible camera-speed slider, keep normal scene-scaled speed as its baseline, retain the user's multiplier across levels, and verify real WASD displacement and slider input before closing this milestone.
5. User-requested checkpoint inspector follow-up: use the source-verified meanings in docs/CHECKPOINT_FIELDS.md for friendly labels, explanations and named behavior/HUD choices. Keep original parser keys, byte offsets and project compatibility; unknown raw integer values remain editable. Mark18/1B as apparently unused and behavior code3 as unidentified. Verify actual delegate edits, signed bounds, undo/redo and project/ROM byte round trips before review.

**Phase 9: Object Models and Animation Preview (user requested)**
1. Add `src/core/object_models.py` and `src/renderer/object_mesh.py` within the existing package. Verify ObjectModel (C0x80; serialized0x58 per tools/fileTypes/objectModel.hpp), model/animation tables28–32, signed16 animation vertex mapping, and delta streams against structs.h, object_models.c and src/hasm/obj_animate.s. Preserve raw bytes and reject malformed spans/indices. Never embed extracted models or textures.
2. Render physical 3D object models and actors referenced by Animation controllers (order0 only, ambient channel20 plus a selectable scene channel). Keep invisible helper objects as gizmos. Preview verified mesh clips with play/pause, scrub, rate and clip selection; use the source node's initial transform. This is an artwork/clip preview, not an emulator for scripted paths, events, AI, physics, particles, shadows or game lighting. Keep procedural fish/butterfly graphics outside this model milestone until their separate renderer is verified.
3. Preserve selection, mouse editing, undo and saved bytes; artwork follows edits. Add independent model visibility and artwork picking. Animate verified sprite sequences without recreating GL textures every frame. Explain preview limitations in the UI and README.
4. Verification Gate: parse all390 stock models and470 animation clips headlessly, test malformed inputs, signed delta/interpolation/static vertices and controller targeting; run full pytest. Native GL verify real mesh/clip changes, pause/scrub/channel controls, level switching, picking, editing and no GL errors. Update compact STATUS.md and stop for review.

**Phases 10–23: Further Editing Milestones**

The user requested a staged plan and deferred object creation/duplication/deletion.
Detailed scopes, prerequisites and individual gates are in
[docs/ROADMAP.md](docs/ROADMAP.md), which is part of this roadmap. Read the relevant
phase there before implementation. Phases 0–19 have passed automated/native
gates, with gameplay testing performed by the user and no sample ROMs generated.
Phase16 with the upright PNG follow-up is implemented in v1.9.1
(700 headless tests and native Qt/GL checks);
see docs/IMAGE_ASSETS.md for PNG export/reimport,
fixed image layouts, quantization, shared uses and version6 overlays. Versions1–5
remain readable with their original writer gates. Gameplay review is performed
by the user, including pending minimap tests. Phase17 artwork is implemented in
v1.10.0 (721 headless tests and native RTX checks); see docs/SPECIAL_ARTWORK.md for projected zippers, procedural animals,
portrait samples and verified runtime-only boost limitations. Project format
and writer gates remain unchanged. Phase18 environment preview (v1.11.0) and
Phase19 existing cinematic paths (v1.12.0) are implemented; see
docs/ENVIRONMENT_PREVIEW.md and docs/CINEMATIC_PATHS.md. The full752-test gate
passes, with native all65-level/263-scene checks and compact four-row toolbars.
The user owns in-game verification, including the edited cinematic path example.
Phase20 feasibility (v1.13.0) adds the read-only capacity audit and isolated
headless structural drafts; see docs/STRUCTURAL_SAFEGUARDS.md. Initial778-test and
native audit/editor checks pass; the full Phase20 structural safety gate is open.
Production structural operations remain disabled:
dynamic/reference bounds and user in-game validation must precede any
Phase21 UI enablement. v1.13.1 adds per-stream source-model inflater checks,
a58-placement noncollidable/no-shadow-texture scenery subset and read-only
RDRAM/BizHawk2.10 snapshot measurements. Two historical hub states are initial
observations, not peak bounds. Full827 tests pass after the Lua main-chunk fix;
nine loader/read-API regressions cover the capture helper. Native snapshot/editor
checks passed previously. See docs/RUNTIME_CAPACITY.md. Normal project
version6/writer permissions are unchanged. v1.13.2 adds a restricted user-run
one-bush research command, with in-memory preview by default and explicit
no-overwrite export for the user's Phase20 gameplay check. See
docs/BUSH_EXPERIMENT.md for exact costs, the additional257-entry interaction
array/fixed shadow buffers and remaining gameplay gates. This is not Phase21 UI.
Full853 headless tests pass (92.94s), including26 research-command tests;
real six-capture preview/help and compileall pass. No persistent review ROM or
emulator run. Next is the user's explicit export/fresh-load gameplay check.
Phase21 scope was explicitly broadened by the user after successful one-bush
gameplay: "dont keep other objects gated ... just do all of them ... I can test
it myself". This supersedes the earlier Phase21 type/reference allowlist gate.
All304 translated object IDs are available for experimental add/duplicate/delete,
including checkpoints/AI/cinematics. Prefer stock placement templates; otherwise
use clearly labelled zeroed source-schema entries. Preserve links/IDs verbatim
with diagnostics; do not invent graph repairs or claim all-type gameplay safety.
Known binary/workspace/ROM/minimum resource bounds remain enforced. Stable editor
identities and v7 structural project rows preserve notes/selection/history;
versions1–6 remain readable. Finish Phase21 headless/native gates and stop before
Phase22; broader runtime testing belongs to the user.
Phase21 implementation is ready in v1.14.0:875 full headless tests pass
(133.79s), final32 affected graph/report/runtime checks pass and native real
palette304/buttons/Ctrl+D/filter/selection/history/v7 reopen/refused base-ROM
export/RTX GL3.3 checks pass. Four toolbar rows are retained. A normal updated
editor is open for review; existing windows were preserved. User broad gameplay
testing remains pending. See docs/OBJECT_EDITING.md and compact STATUS.md.
Phase21 follow-up v1.14.1 fixes cinematic cache ownership when structural
changes shift viewport indices (the RubberTree/BeachTree preview bug). No extra
BeachTree was serialized. Full878 tests pass in129.46s; native RTX GL3.3
add/duplicate/move/delete/history/project reopen and in-memory export checks
pass. Existing user windows/unsaved changes were preserved; restart to load the
fix. Phase22 had not started at v1.14.1.
User Phase21 review, 2026-10-20: v1.14.1 is confirmed fixed, and four added
Central Area RubberTrees were visible in-game with no reported issues there.
New Lua capture verifies exactly four appended map68 entries with all existing
map0/map68 entries unchanged. Runtime snapshot checks pass (265/512 list,
22,224 B free object pool). The representative Phase21 gate is complete;
That review cleared Phase22. It is not a universal type/graph/capacity claim.
The user subsequently authorized Phase22. v1.15.0 implements constrained existing
XYZ deformation with linked stock vertices, unchanged topology/serialized
collision metadata, fixed stock bounds/BSP/PVS envelope, protected water and
unresolved smoothing links. Geometry tab/nudges/mouse gizmo, independent reverts,
v8 geometry projects and exports are implemented. Versions1–7 retain previous
writer permissions. See docs/GEOMETRY_EDITING.md. Full947 tests pass in162.89s;
native RTX GL3.3 picking/numeric/GPU/history/project checks and normal launch
pass. The user performs in-game drive/collision/visibility review before
Phase23. Do not generate test ROMs or touch their unsaved editor processes.
User Phase22 review, 2026-10-20: edited Ancient Lake geometry and collision worked
in-game with no reported breakage. The representative Phase22 gameplay gate is
complete. Phase23 is the next milestone; explain its scope when asked, and begin
implementation when the user authorizes proceeding.
The user authorized Phase23A on2026-10-20. Read docs/STOCK_TRACK_REBUILD.md and
the23A/23B/23C breakdown in docs/ROADMAP.md.23A reconstructs stock records with
exact payload identity, retained opaque data/collision links/BSP/PVS and verified
normal/cutscene runtime generation and compression/ROM budgets. Its optional
stock ROM export uses original-ROM assets, leaving project edits intact. User
gameplay comparison follows automated/native checks.23B follows separate user authorization.
Phase23A is implemented in v1.16.0:1,025 full tests pass in158.85s, including78
stock reconstruction tests. Native selected/all55/cancel/close/dirty-project/GL
checks pass; all55 rebuilt inflated payloads match exactly. Explicit stock export
reuses bounded assembly/CRCs/atomic/source protection. No user-review ROM was
generated automatically. User23A review, 2026-10-20: the exported stock rebuild
worked in Central Area and three early tracks with no reported issues. The
representative23A gameplay gate is complete. The user then explicitly authorized
23B by asking to proceed (and continued the interrupted turn). Read
docs/CUSTOM_TRACK_IMPORT.md: one static segment, at most499 triangles, generated
collision facets/bounds/PVS, retained existing texture slots, staged preview,
v9 projects and bounded normal ROM export. At that stage23C followed the user’s
imported-track collision/racing/visibility review, recorded below. Preserve
their existing windows and do not create persistent test ROMs or run the emulator.
23B automated gate:1,130 tests passed in191.76s (105 import tests), including all55
target templates, new collision/runtime checks, v9 project/history, budget refusal
and in-memory ROM/OBJ isolation. Native RTX4060 GL3.3 preview/Apply/cancel/error,
high-segment selection reset, topology/GPU undo/redo, edit/reopen/stock restore
checks pass. User imported-track gameplay review: the sample replaced Ancient
Lake successfully and the user completed a race with no reported issues. The
representative23B gameplay gate is complete. The user subsequently authorized
Phase23C. Read docs/SEGMENTED_TRACK_IMPORT.md for its local collision certificate,
source limits, protected seam guides, v10 projects and material/surface workflow.
User-reported missing trees during this work were resolved by enabling Sprites;
do not reset visibility preferences or alter their unsaved editor sessions.
Phase23C's representative gameplay gate is recorded below. Do not start
independent milestones without the user's selection/authorization.
Phase23C v1.18.0 automated/native gates pass:1,204 full tests in309.28s,
including74 spatial-import checks/all55 templates; native RTX4060 GL3.3 worker,
surface/Apply/history/project/OBJ/sprite/stock-restore checks pass. The924-face
sample compiles into27 segments. User review, 2026-10-20: they played the sample,
completed the race and reported that everything appeared flawless. This closes
the representative23C gameplay gate and the planned23A/23B/23C sequence. Local
query limits remain; do not infer universal capacity. Preserve existing windows
and wait for the user to select/authorize another milestone.

| Phase | Milestone |
|---|---|
|10|Export budgets and project foundation|
|11|Level settings|
|12|Placement tools for existing objects|
|13|Existing route tools and research workflow|
|14|Track materials and driving surfaces|
|15|Minimap settings|
|16|Texture and sprite replacement|
|17|Remaining physical object artwork|
|18|Environment preview|
|19|Cinematic and actor paths|
|20|Structural object feasibility and safeguards; no creation UI|
|21|Conservative object creation, duplication and deletion|
|22|Editing existing track geometry|
|23|Custom geometry import and track rebuilding|

Phase24 is now explicitly authorized: custom-track MTL/PNG materials, N64
conversion previews/options and source-verified dedicated static 3D texture
assets. Read its scope/gate in docs/ROADMAP.md. Use one staged atomic import,
preserve stock IDs/artwork, old project permissions and unsaved editor windows.
Stop for user review after automated/native checks; do not begin25 or later.
Phase24 v1.19.0 implements canonical dedicated RGBA16/32 static assets, MTL/PNG
previews/options, one atomic import and version11 persistence. Read
docs/CUSTOM_TRACK_ARTWORK.md for source/TMEM/cache/ROM rules. Full1,261 tests and
native RTX/OpenGL workflow checks pass, followed by final affected parser checks.
User review, 2026-10-20: all new textures appeared and the track was completed
without reported issues. The representative Phase24 gameplay gate is complete.
The user has now swapped25/26 and authorized25: course-building helpers.
Read its scope/gate in docs/ROADMAP.md. Implement staged checkpoint ordering,
placement/headings, start-grid layout and actionable course diagnostics with
atomic history and the existing structural/project/ROM protections. Preserve
unrelated data and unsaved windows. Stop for user review after25.
Autosave, crash recovery and project backups were moved after25, then explicitly
deferred again by the user; do not start them.
Phase25 v1.20.0 is implemented under Tools → Routes → Course builder. Read
docs/COURSE_BUILDING.md for source angle/plane/grid semantics, selected-set60
including alternates, explicit reset/removal controls and staged Apply. Full1,299
tests pass in237.24s; final82 affected checks pass in49.73s after the shared-map
report correction (38 course tests). Native RTX4060 GL3.3 real-button/modal,
numeric/ray placement/grid/preflight/history/v11 reopen/cancel/narrow inspector
and normal module launch pass. Original ROM hash is unchanged. Stop for user
gameplay review of starts, lanes and lap completion. Latest user review says the
helpers seem to work and further testing is pending. They deferred autosave again
and asked what is next. The user then explicitly authorized course names only
(26A), in a dedicated window with its own menu item. Latest steering places
Course Names and Texture Browser at the bottom of Edit, after a separator.
No right-panel additions. Dialogue/menu text is excluded and may be selected
later as a separate scope; autosave/recovery remain deferred. Read
docs/COURSE_NAMES.md and docs/ROADMAP.md. Finish headless/native gates, update
compact STATUS.md, then stop for user game-name display review. Preserve unsaved
editor windows; do not generate persistent review ROMs or run an emulator.
Phase26A v1.21.0 is implemented. Full1,409 tests pass in227.42s, including109
course-name checks;246 focused integration checks pass. Native real Edit-menu/
separator/window actions, typing/refusal, staged Apply/history, labels/search/HUD,
retained camera/geometry/artwork/objects/notes, v12 custom-track/structural GUI
reopen, draft discard/reset/original and narrow inspector checks pass on RTX4060
GL3.3. Original ROM SHA-1 unchanged. Read docs/COURSE_NAMES.md for source/font/
63-byte/JP protections and version12 records. Stop for user game-name review;
menu/dialogue text and autosave are not authorized follow-on work.
The user accepted the Blender authoring guide, then explicitly selected global
object properties as Phase27. Read docs/GLOBAL_OBJECT_PROPERTIES.md and its
scope/gate in docs/ROADMAP.md. Implement shared source-traced scalar fields and
compatible existing artwork references in a separate Edit-menu window; preserve
behavior/type/counts, allocation flags, pointers, translation, internal names,
attachment/particle/light/misc arrays and unknown bytes. Include known affected
levels, staged atomic history, v13 projects and exact bounded ROM exports.
Stop after automated/native checks for user gameplay review. Preserve existing
windows; no review ROMs or emulator runs. Behavior conversion, new models/clips,
menu/dialogue text and autosave remain separate scopes.
Phase27 v1.22.0 automated/native gates pass:1,459 full tests in253.12s,
including50 global-object checks;129 final artwork/image checks pass. Native
RTX4060 GL3.3 passes real Edit-menu/modal, numeric/artwork edits/refusals,
two-header atomic Apply, graphics/dependency cache refresh, shared history,
draft discard, v13 GUI reopen and retained camera/object count. Normal module
launch is clean with4x MSAA. See docs/GLOBAL_OBJECT_PROPERTIES.md for the0x78
header/33-35 section layout, exact writable fields and compatibility rules.
Original ROM hash unchanged; existing user windows preserved. Stop for user
gameplay review; no additional milestone is authorized.

Other audit opportunities have separate selectable milestones in docs/ROADMAP.md.
The user subsequently selected Object models and animation editing as Phase28.
Follow docs/OBJECT_MODEL_EDITING.md and its roadmap gate: fixed-topology existing
models/clips, keyframes, verified attachments/collision structures, separate
Edit-menu window, staged history/projects/export. Preserve all open user editors;
no review ROMs/emulator runs. Larger topology/new slots and root/assembly/skeleton
editing remain separate. Finish automated/native gates and stop for game review.

Phase28 v1.23.0 is implemented.1,540 full tests pass in283.02s and81 final
model checks in17.93s. All390 meshes/470 clips are lossless. Native RTX4060
GL3.3 passes real numeric/playback/endpoint/refusal/OBJ/JSON/Apply/cache/history/
v14 reopen checks; Blender4.4 verifies three OBJ round-trips. Original ROM stays
unchanged. Follow docs/OBJECT_MODEL_EDITING.md for fixed topology, protected
frame controls, source bounds and shared-use limitations. Stop for gameplay
review; do not start another milestone automatically.

The user authorized Phase29 static object rebuilding after the model256 sign
extrusion review. Follow docs/STATIC_OBJECT_IMPORT.md and its roadmap gate:
canonical static arrays/batches/materials/references, original opaque prefix,
source command limits, ROM/RAM/inflate diagnostics, staged preview/history/v15
projects. Preserve input OBJ files and every user editor; no persistent test ROMs
or emulator runs. Animated topology/new model IDs remain separate. Stop after
automated/native gates for user gameplay review.

Phase29 v1.24.0 gates pass: all207 static templates rebuild;49 new tests,
180 focused checks and1,589 full tests (285.06s). Native RTX4060 GL3.3 verifies
the exact user extrusion, real dialogs, preview/Apply/live GPU/history/v15 reopen;
Blender4.4 verifies material/UV/color exchange. Sign256 compiles to40 stored
vertices/34 triangles/3 batches, +1,000 B shared model memory/+128 B ROM.
Original ROM and user OBJ files are unchanged. No persistent review ROM or
emulator run. Read docs/STATIC_OBJECT_IMPORT.md and stop for gameplay review;
no follow-on milestone is authorized.

Phase29 review v1.24.1 fixes new-wall material inference: transparent sign decal
walls now inherit aligned source side materials. Explicit batch_N/existing faces
are retained. Legacy original-row reimports retarget current references by
position; unmatched references are refused. Model preview has a Textures toggle.
Full1,593 tests pass in299.92s (53 rebuild checks);134 focused checks and native
RTX GL import/toggle/Apply/live GPU/history/v15 reopen pass. Sign output is now
52 vertices/34 triangles/4 batches, +1,144 B shared RAM/+224 B ROM. The supplied
OBJ extrudes its decal layer, leaving the white backing unchanged; document the
layer distinction rather than altering user geometry. Both original OBJ files,
ROM and existing editor/Blender work remain untouched. Stop for user review.

Do not silently fold them into an active phase. Keep original-ROM length,
capacity refusal and untouched-asset protections. The current exporter can relocate
growing compressed maps; that does not establish safe runtime map/pool/slot budgets
or valid object references. Prove those before enabling structural edits.

## 8. Commands & Quality Gates

The user authorized all four code-audit fixes and related maintenance as
v1.24.2. Project IO is in src/core/project_io.py; shared object dependencies are
in src/core/object_dependencies.py; native checks are in src/ui/smoke_checks.py.
Keep existing versions 1–15 and source protections. Read docs/CODE_AUDIT_FIXES.md
for dependency-ordered header validation, fresh-layout recovery, environment-map
normal classification and live image uses. Stop after verification/user review;
do not begin another feature phase, autosave work or emulator testing.

v1.24.2 gates pass: 1,601 full tests (306.97 s), including eight audit
regressions; targeted native audit checks and the complete relocated smoke suite
pass on RTX4060 GL3.3/4x MSAA (63.4 FPS). Original ROM/OBJ hashes are unchanged.
Native fields also retain drafts on Enter. Preserve older unsaved windows and
stop for user review. No next milestone is authorized.

The user authorized fixing all three second-audit findings as v1.24.3. Edited
header checkpoint-set references are validated against whole candidate map
transactions before installation, including typed/raw/group/history paths.
Assign another set before removing its last main checkpoint. Keep all object
types, stock-value preservation, schema versions and loader protections.
Texture Browser object/history context refresh preserves PNG drafts; numeric
Enter does not invoke Export. See docs/CODE_AUDIT_FIXES.md. Finish focused/full
and native gates, preserve existing user processes and stop for review.

v1.24.3 gates pass: 1,609 full tests (321.09 s), eight new regressions, 194
focused tests (96.99 s), targeted real-control/reopen checks and complete native
smoke at 63.3 FPS on RTX4060 GL3.3/4x MSAA. Original ROM/OBJ hashes are unchanged;
temporary outputs are cleaned. No additional milestone is authorized.

The user authorized both third-audit corrections as v1.24.4: queued geometry and
material cells must retain their originating model through level selection, and
blended scene ranges must share camera-depth ordering. See docs/CODE_AUDIT_FIXES.md.
Keep normal ROM/OBJ workflows and versions1–15; structured extracted model glTF/
JSON remains unsupported. Preserve user windows, original ROM/OBJ files and the
user's gameplay-testing preference. Finish automated/native gates and stop for
review; no next feature phase or extracted-model importer is authorized.

v1.24.4 gates pass: 1,618 full tests (328.27 s), 163 focused checks (51.00 s),
nine new regressions, real XYZ/UV/RGBA-to-level clicks/history, GPU compositing
invariance and all65-level sampled artwork/water/fog rendering. Complete native
smoke passes at63.8 FPS on RTX4060 GL3.3/4x MSAA. Original ROM/OBJ hashes and
existing unsaved windows remain unchanged; a fresh normal v1.24.4 window is open.
Temporary outputs are cleaned. Stop for review; no next phase is authorized.

* **Run Application:** `python -m src.main`
* User-authorized v1.25.0 Course Builder refresh: read docs/COURSE_BUILDING.md.
  Staged all/category cleanup covers both maps; live route/grid editing and
  draft history remain separate from one atomic project Apply/undo. Fresh
  courses may explicitly copy a route to existing mapped sets, retaining header
  mappings. Nearby surface snapping is editor math, not a collision-format
  change. Preserve stock-byte no-ops, project versions, source bounds and user
  sessions. Run focused/full and isolated native gates, update compact STATUS.md
  and stop for gameplay review. No test ROM/emulator or autosave work.
  v1.25.0 gate passes:1,639 full tests,60 final focused checks,all-three-starter
  native route/grid/cleanup/history/Apply/Undo and complete RTX GL3.3 smoke at
  63.8 FPS/4x MSAA. See STATUS.md for precise scope/results. User sessions and
  original ROM are preserved. Stop for user gameplay review; no next phase.
* **Run Tests:** `pytest -v`
* **Headless Core Rule:** Every parser in `src/core/` must be testable via `pytest` without initializing a `QApplication` or OpenGL context.

User-reported Gentle Hills rendering correction, v1.25.1:
Custom track/static model compilers must use at most24 vertices and16 faces per
batch. All55 original tracks and390 object models use at most24; the encoded
32-vertex DMA range is not a safe batch-size assumption. See
docs/RENDER_BATCH_FIX.md and src/core/render_batches.py. Legacy project baselines
throughv15 remain readable; export re-batches oversized ranges without changing
stored project overlays/history, face order, UV/colors, material/collision data
or static attachment/sphere positions. Exact normalized bytes drive budgets and
in-place inflate checks. Keep user ROM/sample/project files and unsaved windows
unchanged. No test ROMs/emulator or new feature phase is authorized.

v1.25.1 gates pass: 1,649 full tests (338.92 s), 378 focused checks, all three
starter tracks through native threaded import/preview/Apply/Undo, and complete
RTX4060 GL3.3 / 4x MSAA smoke at 62.8 FPS. Exact user-exported geometry,
material/pass data, BSP/bounds and collision facets/planes/grid masks remain
identical after export normalization. User files/windows remain unchanged.
Stop for user gameplay confirmation; see compact STATUS.md.

User confirms v1.25.1 Gentle Hills corruption is fixed. Current authorized
v1.25.2 follow-up: checkpoint gizmo arrows show intended local -Z travel,
matching starts, instead of the opposite +Z plane normal. This is a display
change; checkpoint bytes, crossing/AI math and heading writers stay unchanged.
Middle-button drag pans the shared viewport in all four projections; translate
eye/target together in logical pixels, keep camera angles/FOV/speed, preserve
active selection/placement tools, and clean up capture on release/interrupts.
Test shared Course Builder/model/track previews and preserve user windows.
No gameplay ROM/emulator, extra toolbar row or new feature phase is authorized.

v1.25.2 gates pass: 1,684 full tests (332.25 s), 243 focused checks including
35 new cases, native pan lifecycle in all four projections across main/course/
model/track windows, and complete RTX4060 GL3.3 / 4x MSAA smoke at 63.5 FPS.
User files/windows and draft/project state remain unchanged. Stop for user
review; no additional feature phase is authorized.

Current v1.25.3 scenery/wall follow-up: reproduce Central Area's snow doorway
at the supplied camera position before changing state. Screen-facing tree cards
tilted into the cliff at high camera pitch. The editor now derives an upright
preview marker for BHV_SCENERY sprite instances only: world Y up, horizontal
facing toward the camera position in Perspective. Other sprite behaviors and
orthographic views retain screen-facing cards. Match the CPU alpha-aware picker
to the GPU basis; preserve depth occlusion, mixed-artwork grouping, live caches
and hidden/animated frames. This is an editor representation choice, not a
new game flag; see docs/SPRITE_OCCLUSION_FIX.md. Preserve all ROM/project data,
user windows and the gameplay-testing preference. No new phase is authorized.

v1.25.3 gates pass: 1,698 full tests (338.99 s), 58 final focused checks after
the translucent-center sorting refinement, and native affected-doorway/picking/
opaque-and-blended wall occlusion/Top-view checks. Complete RTX4060 GL3.3 /
4x MSAA smoke passes at 63.6 FPS. All 74 sources parse; original ROM SHA-1,
user files, project state and unsaved windows remain unchanged. This preview
fix needs an editor restart, not ROM re-export. Stop for user review.

User-authored About dialog artwork follow-up v1.25.4: preserve their layout,
styles, text and magic codes. Decode game art from the already loaded ROM
into memory, with no embedded/proprietary binary files or implicit ROM search.
Menu reference section18 is read-only, BE u16; menu.c:13787 mask0xC000 and
lower14 texture ID, title menu IDs0x50–0x5A and 15-pixel tile spacing. References
and presentation are documented in docs/ABOUT_ARTWORK.md. Gates:61 initial
artwork/ROM checks,189 final focused image/sprite/texture/context checks, native
About no-ROM/artwork/pop/code/close/repeated-deletion checks and75-source AST.
Original ROM SHA-1, user projects, other source edits and running windows are
preserved. No game ROM/emulator or further feature phase is authorized.

User-authorized compact track OBJ exchange v1.25.5 is complete. Shared
src/core/obj_units.py constants define100 game units per OBJ unit. Track export
writes XYZ×0.01; import API/UI default100 is applied once before rounding and
collision. Offsets stay game units; segmented internal staging explicitly uses1.
Object-model exchange, internal/project/ROM coordinates, origin and artwork stay
unchanged. No legacy migration/guessing was requested. Existing starter files
remain untouched; compact copies/generator output use a separate folder. See
docs/OBJ_SCALE_PLAN.md and docs/BLENDER_TRACK_GUIDE.md. Gates:1,777 full tests
(340.20s),67 new exchange tests/all55 stock exports, isolated Blender4.4 Scale1/1
round trips, owned native control/overlay/Apply/Undo checks, all3 compact starters,
76-source AST and complete RTX4060 GL3.3/4x MSAA smoke at62.7FPS. Original ROM
hash, user source customizations and open sessions are preserved. No test ROMs/
emulator. Stop for user review; no further feature phase is authorized.

User-requested object OBJ units v1.25.6 extend src/core/obj_units.py to both
model_editing.mesh_obj/import_mesh_obj and object_rebuild.rebuild_obj/compile_static.
Writers scale XYZ×0.01; import restores×100 once before rounding/bounds and
material/reference matching. Blender Scale1/1; numeric model fields, clip JSON,
origin, placed-object scale, animation groups and project/ROM units stay native.
No legacy detection/migration. Export fresh OBJ files. Existing topology and
attachment protections remain: Blender dropping model83's loose reference row
is safely refused. Gates pass:1,797 full tests (376.05s),163 focused checks,
all390 lossless meshes/207 static coverage, Blender4.4 animated240/static256/260
round trips/one-unit edits, native three-mode import/extrusion/playback/history,
76-source AST and RTX4060 GL3.3/4x MSAA smoke at62.9FPS. Original ROM SHA-1,
user files/source customizations and open sessions remain unchanged. No gameplay
test ROMs/emulator. See docs/OBJECT_MODEL_EDITING.md and compact STATUS.md.
Stop for user review; no further feature phase is authorized.
