# Feature and editable-data audit — v1.4.0 / USA Rev 1

Historical snapshot before Phases 10–11. Current support is described in README.md
and STATUS.md; level settings and budget/change reports have since been added.

Audited 2026-10-19 against the current application and matching local decomp
in `research/Diddy-Kong-Racing`. These are findings; the staged plan is now in
[ROADMAP.md](ROADMAP.md). No further implementation phase has started.

The user confirms rearranged objects work in-game and the checkpoint HUD cue
changes the actual turn indication. Baseline:474 headless tests and the Phase9
native GL/editor gates. This audit changes documentation only; those tests were
not rerun for the audit. A separate read-only inventory scanned the ROM metadata.

## Current editing boundary

The writable unit is an **existing object-map entry**. XYZ, typed parameters,
unknown/padding parameter bytes and individual bits support undo/redo, projects
and export to a new ROM. The entry's ID and length must stay unchanged
(`src/core/editing.py:181`). The ROM builder at line372 replaces only sections
20/21, then updates the master table and checksums. Other decoded assets remain
read-only. Projects currently store byte changes against original entry indexes
and hashes, so structural editing needs a project-format extension.

There is already more editable gameplay than the UI makes obvious:

- Doors: balloon/key requirements, destination levels, model variants and angles.
- Exits/spawns: destinations, entrances, return spawns, position and orientation.
- Checkpoints/AI nodes: lanes, alternate routes, connections, vehicle sets and HUD cues.
- Existing sound, fog, weather and particle-trigger entries: their stored fields.
- Scenery/collectables: variants, scale/rotation fields and item types where defined.
- Animation nodes: stored target actor, clip, speed, timing and other entry fields.

These are not full simulations of the corresponding game systems. Some fields
still need better labels, units, dropdowns and in-game testing. For example,
editing a fog trigger is supported; editing the default LevelHeader fog is not.
The animation toolbar's scene/clip overrides are preview settings, distinct from
editing stored Animation-entry parameters.

## Missing editor operations

| Feature | Current gap | Main dependency |
|---|---|---|
|Add/duplicate/delete or change object type|Existing entries only; no object palette|Valid entry templates, variable-length map rebuilding, references and project/history migration|
|Copy/paste and multi-selection|One selected object/move transaction|Grouped transforms, property changes and undo|
|Rotation/scale handles|Translation has handles; other transforms use numeric fields where available|Behavior-specific units and axes|
|Placement tools|Ctrl snaps relative to drag start; no terrain drop, surface/object snapping, alignment or orthographic views|Track raycasting and placement UI|
|Dedicated route tools|Checkpoint/AI fields edit, routes display; no route insert/reorder/connect or lane handles|Structural map changes and graph validation|
|Asset browser|No complete thumbnail/name catalog for models, textures and sounds|Reference metadata and previews|
|Research workflow|No per-field notes, saved experiment comparisons or project diff UI|Project annotations and known/unknown/unused field metadata|
|Recovery/testing/sharing|No autosave/recovery, portable patch export or emulator-launch workflow|Separate workflow features|
|Semantic validation|Structural checks exist; no broad link/duplicate-ID/connectivity/resource checks|Source-backed behavior rules|

Object creation must consider runtime budgets, not just compressed ROM space:
`objects.c:48` defines512 object slots and its spawn path logs overflow at2217.
Runtime-spawned actors also use slots, so512 placed entries is not a universal
safe limit. Current ROM export stays within original-ROM padding; arbitrary ROM
growth is not supported. Shared maps/assets also need dependency visibility.
The roadmap follow-up verified471,088 bytes of trailing padding in the original
ROM. Compressed maps may already grow and relocate; runtime limits and linked
objects are separate concerns. The loader also allocates a0x3000-byte map workspace
and0x15800-byte object pool (`objects.c:44–48,978–997`). Safe structural growth must
account for compressed-input staging and dynamic allocations, not only ROM space.

## Additional editable game data

Relative effort estimates are engineering judgments, not delivery estimates or
claims that every unknown is understood.

| Area | Possible edits | Verified source / present limitation | Effort |
|---|---|---|---|
|Level settings|Laps, default/allowed vehicles, world/race type, per-mode AI difficulty, fog/background, skybox, music/instruments, weather/waves|LevelHeader section23; current parser reads a subset and Level inspector is read-only|Lower for established fixed fields|
|Names and text|Level names, menu text, textbox messages and formatting|Sections25/8/6; names decoded; local textbox command parser exists|Lower for names; medium+ for all text types|
|Materials/surfaces|Texture assignment, UVs, vertex colors, transparency, grass/sand/ice/water/boost surface types|LevelModel section27, TextureInfo and batches; no writer|Medium|
|Texture/sprite assets|Replace artwork, anchors, frame sequences, flags and timing|Sections2/4/12 decoded; no replacement/encoding UI|Medium; same-size/same-format replacements are a sensible first gate|
|Minimap|Sprite, rotation, scale, Adventure1/2 offsets and color|Serialized LevelModel fields and game_ui.c:minimap_init; not exposed|Medium|
|Geometry|Move vertices, alter faces, extend roads, import/build tracks|Parser and OBJ exporter exist; no writer/importer|High for topology changes|
|Global object definitions|Shared model/sprite assignments, base scale, draw distance, lighting/shadows, vehicle parts and particles|ObjectHeader section34 and translation35; read-only subset|Medium/high; shared effects|
|Object models/clips|Replace meshes, edit vertex keyframes, attachment points and collision spheres|Sections29/30/32 decoded/previewed; no editor or asset replacement|High|
|Cinematics|Actor/camera path drawing, motion scrubbing, timing, loops, fades, sound/message events|Node fields edit; preview plays mesh clips at initial transforms|Medium/high for faithful playback|
|Racer balance|Character weight, handling, acceleration curves and hitbox tables|Named MISC assets in section15, consumed by racer.c|Medium, with field-by-field verification|
|Weapons and AI|Balloon upgrade-to-weapon mapping, AI behavior tables, difficulty|MISC_BALLOON_DATA, section0 and level AI fields|Medium for traced tables; not all rules are data-driven|
|Menus/progression|Track-menu/hub/main/battle/boss lists, title demos, magic-code strings/descriptions|Named MISC assets and extractor routines|Medium for lists; new mechanics require code work|
|Audio|Choose existing level music/sounds; later replace music/instruments/effects|LevelHeader music, sound-trigger entries, audio section39|Lower for choosing references; high for bank import/rebuild|
|Particles/weather assets|Particle appearance, emitter behavior, weather graphics and attachments|Sections19/41/43, particles.h/c; extractor leaves particles raw|Medium/high|
|HUD/fonts|Element artwork/mappings and glyphs|Sections17/18/44/46 and sprite/texture references|Medium/high; some layout is compiled code|
|T.T. ghosts|Visualize/import/edit staff trajectories, times and metadata|Sections48/49; local GhostHeader8 bytes, GhostNode12 bytes|Medium; timing/game constraints need validation|

Key distinctions for future writers:

- LevelHeader C size is0xC4, serialized size0xC8. The apparent C AI pointer
  at0x20 is inline serialized difficulty data. Unknown bytes must be preserved.
- Surface type belongs to a **level-model TextureInfo entry**, rather than its
  global texture pixels. Changing a road image alone does not make it ice.
  `src/hasm/collision.c:149` reads this field; `racer.c:61–90` contains compiled
  traction/slide/sound tables defining the response to those surface categories.
- The game generates collision planes at load time (`tracks.c:2832` onward)
  using serialized facet references and geometry. Geometry import needs coherent
  facets, bounds, segments, visibility/BSP, batch constraints and memory budgets.
  Runtime collision pointers must not be interpreted as serialized ROM arrays.
- Local buildLevelModel.cpp/extractLevelModel.cpp only pass through raw level
  binaries. They do not supply a completed custom-track compiler.
- Weight/handling/acceleration have ROM assets. Some physics, weapon rules and
  unlock thresholds are compiled constants/control flow; those require a
  separate verified code-patch workflow, not just another asset editor.
- Changing magic-code strings does not add new cheat behavior. Adding new level
  IDs/counts also involves menus, game code and save/progression assumptions.
- Decomp asset sources remain view-only; model/animation preview does not import
  their structured glTF/JSON exports. OBJ export contains track geometry only.

## Remaining artwork and preview gaps

The read-only scan examined all138 map slots /9,426 entries and compared their
model types with the application rendering allowlists. Concrete gaps include:

- **92 GroundZipper entries:** behavior82 is not in the sprite-art allowlist.
  Its loop sets SHADOW_ONLY; the ground image needs the projected-shadow/decal
  renderer rather than a normal billboard. Entry properties already edit.
- **40 Fish,25 Butterfly,8 CharacterFlag and1 Boost entries:** model type4 uses
  runtime geometry selected by objects.c:render_3d_misc. Portraits and boost
  graphics also depend on runtime state.
- Particles, lava/bubbles, weather, lens flares and projected object shadows.
- Racer/vehicle-part assemblies, gameplay-spawned actors, procedural movement,
  buoy/bridge interactions and progression-dependent visibility.
- Scripted actor/camera path motion and events. The current30-second timeline
  is an artwork preview range, not a whole-cutscene duration/state machine.
- Animated/scrolling track textures, waves, skyboxes, level fog and full game
  lighting/environment mapping. Model lighting currently uses a neutral preview.

Other excluded entries are intentionally invisible helpers: checkpoints, camera
controls, AI nodes, exits, audio regions and triggers. Their debug sprites/models
should remain gizmos rather than being treated as missing in-game scenery.

## Planned milestones

The user requested that object creation/duplication/deletion be deferred.
[ROADMAP.md](ROADMAP.md) replaces the audit's original suggested order with
Phases10–23: export/project safeguards; level settings; existing-object placement
and routes; materials/surfaces; minimap; textures/sprites; remaining artwork;
environment and cinematic paths; structural-object feasibility, then conservative
creation/deletion; constrained geometry editing, then custom track rebuilding.

Other findings have separate selectable milestones for text, racer balance,
weapons/AI, menus, global objects, models/clips, audio, effects, HUD/fonts, ghosts
and recovery/sharing. Every implementation milestone has its own verification
gate and review stop. No implementation phase has started.

## Evidence pointers

Paths are relative to the local decomp unless labeled application.

- Application src/core/editing.py:181,299,372; src/ui/object_inspector.py:257;
  src/core/rom.py:32; src/core/object_models.py:PHYSICAL_MODELS;
  src/core/textures.py:WORLD_SPRITE_BEHAVIORS.
- tools/dkr_assets_tool_extract.json:sections and named files.
- include/structs.h:430(LevelHeader),693(segments),737(LevelModel),798(ObjectHeader).
- tools/dkr_assets_tool_src/fileTypes/levelHeader.hpp and textureInfo.hpp.
- src/game.c:465–615 (weather/fog/music/vehicle and checkpoint selection).
- include/level_object_entries.h (door/exit/spawn/animation/trigger schemas).
- src/objects.c:48,980,2217,render_3d_misc; src/object_functions.c:954,1082,
  1418,5811,6354 (runtime object/render rules).
- src/tracks.c:2832–2940; src/game_ui.c:3297,3668,3783 (model/minimap).
- src/hasm/collision.c:149; src/racer.c:61,320,4232,8699 (surface and stat uses).
- tools/dkr_assets_tool_src/extract/extractTypes/extractMisc.cpp, extractGameText.cpp,
  extractTTGhost.cpp and fileTypes/gameText.hpp,ttGhost.hpp. Textbox parsing exists;
  that tool's dialog branch is still raw.
- This project's docs/OBJECT_ANIMATION_FORMAT.md has the detailed animation trace.
