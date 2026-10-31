# DKR Workshop: current features and update opportunities

Audit date: 2026-10-30. Source version: **0.26.0 public beta**.

DKR Workshop already provides a substantial course and asset editor: custom
track compilation, placed-object editing and creation, route/start-grid building,
texture replacement, shared object properties, and object mesh/animation editing
all have application workflows. The strongest update opportunities are better
creator workflows and additional game-data editors, rather than basic viewing
or object movement.

This report describes the current source tree. It does not establish which
features were included in a previously published download; there is no Git
repository at the workspace root to provide that release comparison. Existing
capabilities below should only be advertised as new if the public release lacks
them. The old `docs/FEATURE_AUDIT.md` explicitly describes a much earlier build;
many of its missing features are now implemented.

**Current feature inventory**

| Area | Implemented now | Important boundary |
| --- | --- | --- |
| ROM and project workflow | Original USA Rev 1 ROM loading; `.z64`, `.v64`, `.n64` normalization; `.dkrproj` save/open; shared undo/redo; dirty-state prompts; separate edited-ROM export; checksums, relocation and original-path protection | Original USA 1.1 identity is required. Projects store edits against that original. Exported ROMs cannot be opened as editable replacements for the original/project. |
| Level browser and viewport | Searchable stock level catalog; tracks, hubs and cutscene stages; textured and vertex-colored geometry; sprites, object models and supported special artwork; independent visibility filters | The viewport previews supported graphics and data; it does not execute the game. |
| Camera and editing guides | Fly, orbit, pan, fit/focus; Perspective/Top/Front/Right views; independent movement-speed slider; adaptive working grid, surface/selection plane controls and corner axes | No persistent camera-bookmark or saved workspace UI was found. |
| Placed objects | Picking artwork/markers/list rows; filtering; multiple selection; typed properties, XYZ, raw bytes/bits; add/duplicate/delete through the full 304-type catalog; template provenance; live preview | Entry prefixes and behavior layouts remain protected. Adding an existing type is supported; creating a new behavior/type is not. Copied links/IDs can require manual review. |
| Placement | Mouse translation, supported rotation/scale handles, group transforms, shared-property edits, Step snapping, surface placement, drop-to-ground, axis alignment, copy/paste position | Rotation/scale depend on the object's verified fields. Position copy/paste exists; general object/group clipboard transfer and reusable prefabs were not found. |
| Track deformation | Vertex/face picking, table and mouse XYZ edits, automatic linked-vertex movement, undo/revert and export | Existing topology and spatial envelope stay constrained. Protected water/seam data is not freely editable. This is not a built-in mesh modeling tool. |
| Custom track import | OBJ replacement with independent preview, target selection, scale/offset/winding controls, material mapping, generated collision, spatial segments/BSP, resource checks, atomic Apply and stock restoration | Replaces an existing geometry ID. Track import does not realign objects, checkpoints or minimap artwork automatically. Conservative visibility is generated; there is no occlusion optimizer. |
| Track materials | Visual batch picking and material thumbnails; texture assignment; driving surfaces; shared course-material edits; per-corner UV editing/transforms; vertex RGBA and supported rendering flags | Texture assignment normally affects a whole batch. Changing a PNG alone does not change driving physics. |
| Custom track artwork | OBJ/MTL/local PNG staging; appended dedicated 3D textures; resize/quantization preview; RGBA16/RGBA32, opaque/cutout/blend and clamp settings | Dedicated assets are static single-frame textures. This is not a general new sprite/animation asset creator. |
| Course Builder | Separate staged viewport; clear all/category/race objects; click/drag/insert/reorder/reverse checkpoint routes; headings and road snapping; copy routes to mapped vehicle sets; place/aim/fit an eight-racer grid; draft undo/redo; one project Apply | Works inside existing levels/maps. It does not create new level slots, a campaign, or automatically derive an ideal AI line from the road mesh. |
| Routes and AI links | Checkpoint-set/lane visualization; four lane positions and behavior selectors; drag lane points; directed AI-node link selection; duplicate/dangling-reference diagnostics | Edits existing route data. It does not simulate racer AI or replace global AI/weapon behavior tables. |
| Level settings | Laps, default/allowed vehicles, vehicle checkpoint sets, existing AI preset references, skybox, fog/background/FOV, existing music and channel mask, weather settings | World/race type, geometry/map references and unknown header fields stay protected. Weather and audio values save but are not played in the viewport. |
| Course names | Separate multi-course English/German/French editor with font/width feedback, staged Apply, project persistence and ROM export | Printable supported ASCII only, at most 63 name bytes. Japanese bytes are retained. Dialogue, menu text and general localization are not editable. |
| Texture and sprite browser | Thumbnails/filtering/frame selection; PNG export and staged replacement with N64 quantization preview; sprite anchors; texture timing; known shared uses; revert/undo | Stock dimensions, format, palette, frame count and tile layout remain fixed. Existing frames can be replaced; longer sequences/new sprite definitions cannot be authored. |
| Minimap | Existing sprite selection, scale/rotation/offsets, Adventure variants, tint, marker alignment preview and PNG exchange | No automatic minimap generation from custom track geometry was found. |
| Global object properties | Shared definition scale/distance/lighting/shadow/water-effect fields; compatible artwork substitutions; affected-use lists; multiple drafts and atomic Apply | Behavior, model type, array counts, pointers and unknown data stay protected. No new global object definitions or behavior conversion. |
| Object models | Separate preview/editor; existing vertex/UV/color edits; attachment references; existing collision sphere centers/radii and broad-phase distance; OBJ import/export; draft Apply and known uses | Shared models affect multiple instances. Static topology can be rebuilt, but existing texture/lighting signatures and reference identities constrain the import. |
| Static object rebuilding | Added/deleted/extruded faces through OBJ; existing batch materials and UVs; canonical rebuilt arrays, collision/normal memory diagnostics and project/export support | Only eligible models without clips; no new model IDs. Object OBJ export does not include a complete MTL/PNG package. |
| Model animation | Existing vertex-animation clip playback/scrubbing; group XYZ keyframe edits; JSON clip import/export; protected frame/group metadata and delta validation | Fixed group/frame counts and animated topology. No Blender skeleton/action importer, new clip slots, retargeting or root/control-track authoring. |
| Environment and cinematics | Saved sky/fog/background preview; texture animation/scroll; approximate waves; supported animals/portraits/projected zippers; actor/camera paths, node fields/events, scene selection and camera preview | Audio/event execution, particles, live racer substitutions, progression state and exact game lighting/water behavior are not simulated. |
| Export/resource diagnostics | Exact compressed ROM budget and changed-asset report; known dependencies/shared levels; structural checks; stock track rebuild checks; load/compare raw RAM or verified BizHawk snapshots | ROM storage is separate from runtime RAM. Snapshot reports are observations, not a universal whole-game capacity guarantee. |

Stock-data coverage represented by the implementation/tests includes 65 level
records, 55 track models, 304 object definitions/types, 390 object meshes,
470 clips, 207 static rebuild templates, 1,416 3D textures, 916 2D textures and
193 sprites. Those counts describe the stock source data, not universal support
for every gameplay behavior or unrestricted asset creation.

Some hard limits matter when planning feature claims:

- Track import accepts up to 499 triangles in single-segment mode. Spatial mode
  caps input and stored output at 6,000 triangles, including generated seam
  helpers in the stored output, and at 127 segments. Local density, collision,
  draw-command and heap checks can reject a smaller track.
- Dedicated custom textures use dimensions from 8, 16, 32 and 64, with at most
  4 KiB of texels per texture. The project caps additions at 128 textures;
  these are editor bounds, not promises of available runtime memory.
- Static model rebuilding caps stored geometry at 4,096 vertices and 2,048
  triangles, with further batch, reference and memory checks.
- Existing clip changes retain frame/group counts and signed8 changes between
  consecutive keyframes. Arbitrarily large deformations cannot be encoded.
- Export retains the original 12 MiB ROM length. Asset growth shares existing
  trailing padding; arbitrary ROM expansion is not implemented.

**Existing tools that still have clear room to grow**

| Gap | What an update could add | Scope judgment |
| --- | --- | --- |
| Object reuse and discovery | Thumbnail/3D object catalog, favorites, named presets, reusable object groups and cross-course copy/paste | Medium. The catalog is currently a searchable text list; linked object IDs need deliberate transfer rules. |
| Complete Blender exchange for objects | Object mesh OBJ + MTL + PNG package, matching track export's convenience | Small to medium. Geometry/UV/batch exchange exists; packaging and shared texture naming are the main additions. |
| Batch artwork workflow | Bulk PNG export/import with asset IDs and orientation metadata, sequence sheets and changed-asset filtering | Medium. Existing conversion and validation can be reused, while imports still need atomic review. |
| Custom-track finishing | Generate a minimap image from the new road mesh and assist map scale/offset alignment | Medium. The existing minimap panel currently edits a retained sprite/image manually. |
| Scene organization | Persistent named selections/groups, visibility/lock controls, camera bookmarks, recent projects and saved workspace preferences | Small to medium depending on persistence and history design. These are workflow additions, not missing ROM parsers. |
| Richer route authoring | Better visual alternate-branch creation, lane generation/continuity tools and clearer diagnostics for authored courses | Medium. Basic route insert/reorder/reverse, lane editing and start grids already exist. |
| Broader texture/sprite creation | New sprite definitions, tile layouts, frame counts and animated custom artwork | Medium to high. Fixed-layout frame replacement already exists; allocation/reference changes are the missing part. |
| Broader animated models | New frames/clips, animated topology changes, mapping/retargeting and richer exchange | High. Existing signed-delta encoding, shared groups, controller bytes and attachment semantics constrain this. |
| More flexible track authoring | Better visibility compilation, density/performance guidance and supported new wave geometry | High. Import already builds collision/BSP; the remaining issues are source runtime constraints and additional authoring features. |

Effort labels are relative engineering judgments, not delivery estimates.

**Game systems that do not yet have dedicated editors**

| System | What already exists | What is missing |
| --- | --- | --- |
| Dialogue and menus | Course-name editor and some existing event/message references | Textbox/menu string editing, commands/formatting, text previews, font-aware localization and rebuilt text tables |
| Racer balance | Per-level references to stock AI presets; selected model/header properties | Dedicated weight/handling/acceleration/hitbox data editor and comparisons |
| Weapons and global AI | Existing balloon/object properties and checkpoint lane behavior fields | Balloon upgrade/weapon mappings and global AI-table editing; compiled game rules would require separate code work |
| Progression and menu structure | Existing door/exit/unlock parameters can be edited as object fields | Track/hub/trophy/menu-list authoring, coordinated progression tooling and new level IDs/save expansion |
| Audio | Existing sequence IDs, channel masks, sound-trigger and cinematic request fields | Sound/music browser with playback, audio bank/sequence/SFX import and rebuilding |
| Particles/weather effects | Existing emitter/trigger fields and saved weather settings | Effect definition editor, particle rendering, weather preview and broader lighting/shadow simulation |
| HUD and fonts | Existing image replacement and read-only font metrics for course names | Dedicated element mapping/layout and glyph/font table authoring; some layout is compiled code |
| T.T. ghosts | Ghost-related placed-object schemas | Dedicated ghost trajectory/time browser, visualization and import/export/editor |
| Sharing | Projects, complete edited ROM export and track/model/image exchange | Built-in BPS/xdelta-style patch export, mod manifest/package export and DKR-R export workflow |
| Additional ROM revisions | Byte-order normalization for the supported original | USA 1.0/PAL/Japan support and a deliberate modified-ROM inspection workflow |

The absence of a dedicated editor does not mean every related value is
uneditable. For example, a door's requirement, an audio trigger's sound ID, or
an emitter reference may already be exposed in object parameters. Those fields
do not amount to an audio-bank, progression or particle-definition editor.

**Deliberately deferred or separate work**

Autosave, crash recovery and rolling backups are absent and were explicitly
deferred in the existing project instructions/roadmap. They remain valid future
options, but this audit does not reactivate that work. Manual project saving,
atomic publication and unsaved-change prompts already exist.

An emulator launcher and full gameplay simulation are also absent. The current
workflow deliberately leaves gameplay testing with the user. Preview fidelity
should be described per system; recreating the entire game inside Workshop is
not a prerequisite for a useful editor update.

The separate DKR-R compatibility fork/package must not be counted as a shipped
Workshop menu feature. The prior status records a minimal whole-ROM package with
host checks and user gameplay review still pending. Workshop has no integrated
DKR-R/patch export action, and its source was not changed for that fork.

**Suggested update themes**

1. **Creator workflow update.** Visual object browsing, favorites/presets,
   reusable groups/cross-course transfer, and object OBJ/MTL/PNG export. This
   builds on mature editors and would reduce repeated setup work. Linked-group
   transfer should be a defined sub-scope rather than generic byte copying.
2. **Custom course finishing update.** Generated minimaps, batch artwork tools
   and improved route/alternate/lane guidance. Custom tracks, dedicated textures
   and the eight-racer Course Builder are already the foundation; this update
   would make completed courses easier to produce.
3. **Racer and item tuning update.** A focused data editor for racer stats and
   verified balloon/weapon mappings. This adds a new kind of modding beyond level
   construction. The local decomp exposes relevant MISC consumers; formats,
   validation and writers still need implementation.
4. **Text and presentation update.** Dialogue/menu text first, with font-aware
   previews and separate later HUD/font expansion. Keep progression restructuring
   and new mechanics separate from string editing.
5. **Advanced assets update.** Expanded sprite/texture animation creation and,
   later, animated-model topology/clip authoring. These are substantial compiler
   and reference-management milestones, not small extensions to the current
   Import buttons.

Patch sharing is a useful independent update theme, particularly once the
DKR-R user gameplay review establishes the intended compatibility scope. Other
regions, new level slots, ROM expansion and compiled gameplay changes should be
treated as separate major projects.

My first choice is the **creator workflow update**, followed by **custom course
finishing**. They improve the strongest existing capabilities and offer visible
benefits without first requiring a new game-data subsystem. If the priority is
a larger new headline feature, choose **racer/item tuning** or **dialogue/menu
editing** instead. No implementation is started by this recommendation.

**Documentation corrections identified during the review**

- `docs/FEATURE_AUDIT.md` is historical. Its missing object creation, placement,
  material, minimap, texture, geometry and animation tools are largely present.
- `README.md` says other supported sources are view-only. The actual ROM loader
  rejects non-original/modified ROMs outright. Extracted assets are a separate
  backend, and their File-menu action is commented out. Public copy should make
  that distinction explicit.
- Historical phase documents retain earlier pending-gameplay notes and older
  version numbers. They are useful development evidence, but should not be used
  as a current release checklist.
- Existing complete features need a comparison with the last public package
  before writing a changelog. This source review alone cannot establish that
  publishing history.

**Source evidence and validation**

Key evidence paths are absolute, rooted in this workspace:

- UI entry points and source loading: [main_window.py](D:/RomHacking/n64/dkr/src/ui/main_window.py:257), [rom.py](D:/RomHacking/n64/dkr/src/core/rom.py:161).
- Supported writers/history/export: [editing.py](D:/RomHacking/n64/dkr/src/core/editing.py:54), [project_io.py](D:/RomHacking/n64/dkr/src/core/project_io.py:27).
- Objects and placement: [object_palette.py](D:/RomHacking/n64/dkr/src/ui/object_palette.py:12), [placement_panel.py](D:/RomHacking/n64/dkr/src/ui/placement_panel.py:19), [placement.py](D:/RomHacking/n64/dkr/src/core/placement.py:24).
- Course/route tools: [course_builder.py](D:/RomHacking/n64/dkr/src/ui/course_builder.py:120), [course.py](D:/RomHacking/n64/dkr/src/core/course.py:308), [route_panel.py](D:/RomHacking/n64/dkr/src/ui/route_panel.py:28).
- Geometry/artwork limits: [track_import.py](D:/RomHacking/n64/dkr/src/core/track_import.py:28), [track_segments.py](D:/RomHacking/n64/dkr/src/core/track_segments.py:28), [track_artwork.py](D:/RomHacking/n64/dkr/src/core/track_artwork.py:25).
- Materials/images/minimap: [material_panel.py](D:/RomHacking/n64/dkr/src/ui/material_panel.py:27), [image_browser.py](D:/RomHacking/n64/dkr/src/ui/image_browser.py:119), [minimap_panel.py](D:/RomHacking/n64/dkr/src/ui/minimap_panel.py:92).
- Settings/names/shared definitions: [level_settings.py](D:/RomHacking/n64/dkr/src/core/level_settings.py:60), [course_names.py](D:/RomHacking/n64/dkr/src/core/course_names.py:18), [global_objects.py](D:/RomHacking/n64/dkr/src/core/global_objects.py:49).
- Models/animation: [model_editing.py](D:/RomHacking/n64/dkr/src/core/model_editing.py:136), [object_rebuild.py](D:/RomHacking/n64/dkr/src/core/object_rebuild.py:36), [model_editor.py](D:/RomHacking/n64/dkr/src/ui/model_editor.py:144).
- Preview/resource boundaries: [environment.py](D:/RomHacking/n64/dkr/src/core/environment.py:1), [cinematics.py](D:/RomHacking/n64/dkr/src/core/cinematics.py:1), [export_report.py](D:/RomHacking/n64/dkr/src/ui/export_report.py:19).
- Future racer/item data consumers: [local racer.c](D:/RomHacking/n64/dkr/research/Diddy-Kong-Racing/src/racer.c:4232), [balloon mapping consumer](D:/RomHacking/n64/dkr/research/Diddy-Kong-Racing/src/racer.c:320).

All 128 application/test Python files parsed successfully with `ast.parse`
(80 application files and 48 test files). The current automated suite contains
518 test functions before parametrization. The complete automated suite passed:
**1,820 passed, zero failures/errors/skips, in 345.50 seconds**. This includes
the existing widget checks; the separate full native OpenGL smoke workflow and
gameplay were not rerun. The sandbox blocked native dependency DLL loading, so
the successful suite used normal host permissions with third-party pytest
plugin autoload disabled. Temporary test/export fixtures were removed afterward;
the JUnit result is retained at
[feature-audit-20261030-tests.xml](D:/RomHacking/n64/dkr/artifacts/feature-audit-20261030-tests.xml).
No application code was changed.

<details>
<summary>Related DKR-R handoff preserved from the preceding STATUS.md</summary>

This is separate from the Workshop feature inventory above.

Removed the extra Windows ROM-picker source/target/dependency/executable.
Retained original/layout validation, complete immutable cartridge handoff,
per-export profiles and offline/mod isolation. Tests stay host-only. Local
v80-only build support remains needed: user has no v77 original.
Workshop application code, generated guest code and dependency pins unchanged.
Ask before any Workshop code change; no upstream contact/publication authorized.

New package: artifacts/DKR-R-Workshop-minimal (1.0.12-workshop-minimal.1).
Previous working preview preserved. Passes: 62 native ROM checks, actual PI
DMA/PIO/reload, four real Workshop exports entirely in RAM, four packaged-native
startup refusals, x64/helper/asset/22-notice checks. All 142 host tests have passing
results: 139 initial, three Windows process/save tests pass with normal permissions.
Guard and diff checks pass. Full tooling still flags five intentional edits
against the historical v1.0.7 capsule; no pins/exemptions changed to suppress it.
Original ROM SHA-1: 6d96743d46f8c0cd0edb0ec5600b003c89b93755.

No game/emulator was launched or review ROM generated for that work.
Next: user retests their edited ROM using existing DKR-R.exe with --rom for the
original USA1.1 and --workshop-rom for their edited export (see package README).
Details: research/DKR-R-workshop/docs/WORKSHOP_ROM.md and
research/DKR-R-workshop/docs/notes/2026-10-30-workshop-rom.md.

</details>
