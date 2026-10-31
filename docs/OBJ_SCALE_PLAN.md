# Plan: smaller track OBJ coordinates for Blender

Status: implemented and verified as v1.25.5. The user
requested compact export/import and explicitly waived existing-project compatibility.

Gates pass:1,777 full tests (340.20s),67 new exchange checks including all55
stock exports, isolated Blender4.4 Scale1/1 on three stock tracks/custom Gentle
Hills, owned native export/import/overlay/history checks and complete RTX4060
GL3.3/4x MSAA smoke at62.7FPS. New compact copies of all3 starters retain original
integer geometry and pass default100 artwork previews. Original files/sessions
remain untouched; no gameplay ROM/emulator was used. Results are recorded in
STATUS.md and artifacts/compact-obj-verification/.

## Intended workflow

Use a fixed **1:100 exchange scale** for track OBJ files:

```text
Editor/game: 10000 units
  → export ×0.01
OBJ / Blender: 100 units
  → import ×100
Editor/game: 10000 units
```

Blender uses **Import Scale1**, **Export Scale1**, **−Z Forward / Y Up** and
**Clamp Bounding Box0**. The editing suite performs the conversion. No manual
rescaling in Blender and no automatic size guessing are needed.

Ancient Lake becomes about58.95×105.11 Blender units horizontally; Gentle
Hills would be62×48 at the same convention. This is a convenient modeling
scale, not a claim about physical meters in the original game.

This change covers the track exporter and track importer. Existing object
model/animation OBJ exchange has a separate implementation and remains outside
this work. Compatibility/migration tools for older raw-unit files or projects,
automatic metadata detection and alternate legacy export modes are omitted.
Existing user files will not be rewritten or removed.

## 1. Define one shared scale convention

Add a small pure core module, for example `src/core/obj_units.py`, defining:

- `GAME_UNITS_PER_OBJ_UNIT = 100.0`
- `OBJ_UNITS_PER_GAME_UNIT = 1.0 / GAME_UNITS_PER_OBJ_UNIT`

Use these constants in track export, track import defaults and the UI instead
of scattering unrelated numbers through the code. Keep the editor's internal
models, geometry edits, objects, routes and ROM writers in game coordinates.

## 2. Scale track exports down

Change `src/core/exporter.py::export_obj()` so only each written vertex's XYZ
is multiplied by0.01. Preserve signs, world origin and enough decimal precision
to recover one-game-unit steps. Do not center or rotate the track additionally.

Leave vertex colors, UVs, triangle winding/order, groups, materials, PNGs,
helper-face filtering and export publication behavior intact. Export must not
mutate the loaded model's arrays. Add a plain-language OBJ header comment
describing the units for humans; importing must not depend on that comment
surviving Blender.

The normal **File → Export Wavefront .OBJ** path and direct track export API
will share this default. Existing counts in `ExportResult` retain their meaning.

## 3. Scale track imports back up

Set the track `ImportOptions` default scale and the existing import dialog's
Scale field to100, using the shared constant. The displayed value is the actual
multiplier applied exactly once, rather than a hidden100× factor multiplied
again by the visible control.

For both single-segment and spatial compilation:

```text
game XYZ = round(OBJ XYZ × import scale + game-coordinate offset)
```

Apply conversion before game-space integer rounding, signed16 checks, spatial
partitioning, collision generation and budget validation. Keep offsets in
game units and label them clearly. At the default100× import, a0.01 change in
an OBJ coordinate represents one game unit.

The staged preview remains in game units, matching existing starts,
checkpoints, scenery and racing lines. Applying an import uses the current
undo/project/export machinery. No change to the ROM's coordinate format or
project format is expected: only the external OBJ convention changes.

Retain the existing positive finite scale validation and manual multiplier
control for deliberate resizing. The normal default is100. Audit internal
compiler call sites and test fixtures so they express their incoming units
explicitly, rather than accidentally multiplying already converted geometry.

## 4. Update the Blender instructions and future samples

Update `docs/BLENDER_TRACK_GUIDE.md`, custom/segmented track guides and relevant
UI text together:

- Editing-suite export already produces compact coordinates.
- Blender import/export both use Scale1, −Z Forward / Y Up and no clamp.
- Editing-suite track import defaults to100 and restores game coordinates.
- Standard Blender viewport clipping is practical with the compact geometry;
  retain sensible near/far values and frame the selected track.

Update future starter-track generation/export instructions to use the same
external convention. Do not silently rewrite the user's existing `.blend`,
OBJ or project files. Prior large-coordinate examples will no longer be the
default workflow; no compatibility implementation is required.

## 5. Verification gates

### Headless math and export/import checks

- Check stock exports across all55 geometry records: output XYZ equals original
  XYZ/100; original arrays and unrelated export content remain intact.
- Verify reciprocal scaling for positive, negative, zero, near-limit and
  one-game-unit coordinate differences, including coordinates far from origin.
- Verify the compiler rounds only after scaling and rejects genuinely
  out-of-range results. Test both single-segment and spatial modes.
- Check that UVs, colors, face winding, material assignments and helper filtering
  are unaffected by coordinate conversion.
- Confirm default UI/API multipliers agree and that user scale adjustments do
  not cause a second automatic conversion.
- Exercise a valid custom track through export/reimport, preview, Apply,
  Undo/Redo, project save/reload and in-memory ROM export validation. Compare
  intended geometry, surfaces/collision queries and alignment with placed objects.

Stock exports can be used for coordinate/Blender checks without promising that
every untouched stock mesh satisfies the separate custom-topology compiler.

### Isolated Blender and native editor checks

- In a separate background Blender4.4 process, import the suite's compact
  OBJ at Scale1 and export at Scale1. Verify dimensions, game-space positions,
  winding and UV/material handling after the suite's100× import conversion.
- Include Central Area, Ancient Lake, Fossil Canyon and a valid custom starter
  track. The prior check already established that an inverse100× pair can
  recover positions with less than0.001 game-unit fractional error.
- Use owned editor windows to check the real export/import controls, converted
  preview, placed-object overlays and Apply/Undo. Preserve the user's running
  editor and Blender sessions. Do not generate gameplay test ROMs or run an
  emulator; use in-memory export validation as needed.

Finish by running relevant export/import/material/segmentation tests, then the
required regression checks for any changed paths. Update the application version,
README and compact STATUS once the implementation gates pass.

## Completion criteria

The user can export a track, edit it comfortably in Blender with both Blender
scale settings left at1, and import it through the default100× conversion with
its game-world size and placement restored. No legacy migration or guessed
unit detection is part of this milestone.
