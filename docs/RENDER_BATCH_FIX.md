# Imported geometry rendering correction — v1.25.1

The Gentle Hills gameplay report exposed a compiler error: custom track imports
could load 25–32 vertices in one render batch. Static object rebuilding shared
the same assumption. The command field's encoded range was mistaken for the
game's supported batch envelope. OpenGL could display these arrays normally,
so the editor preview did not reveal the game rendering problem.

The user's exported Ancient Lake model contained 11 segments and 73 batches;
oversized grass/barrier batches matched the stretched barrier polygons in the
screenshots. Road batches were mostly within the stock range.

## Local evidence

- `research/Diddy-Kong-Racing/tools/dkr_assets_tool_src/builder/buildTypes/buildModel/buildModelBatch.cpp:11–26`
  uses a 24-vertex boundary and limits triangle loads to 16.
- All 55 original Rev1 track models and 390 object models were decoded and
  audited: no batch loads more than 24 vertices; both groups reach 24.
- `include/f3ddkr.h:161–174` can encode 32 vertices. This establishes the field
  width, not that all 32 entries are safe for the game's vertex loading path.
- `src/tracks.c:1885–1980` emits each batch as one vertex load, then polygons.

New compilation uses at most 24 vertices and 16 triangles per batch, including
spatial seam guides. Mesh geometry is unchanged; extra batches and duplicated
boundary rows provide the same triangles with smaller vertex loads.

## Existing projects

Save the project, reopen it in v1.25.1 and export a new ROM. Old project baselines
remain valid and editable. Export splits oversized track/static model batches
automatically without changing the project's stored overlays or undo history.
Reimporting the OBJ or rebuilding checkpoints/start positions is unnecessary.

Normalization preserves face order, world positions, RGBA, signed corner UVs,
material flags, opaque/translucent boundaries, segment bounds/BSP and collision
face IDs. Static attachment/sphere indices remap to the same vertex positions.
ROM budget reports use the actual normalized decoded/compressed bytes; existing
runtime, capacity, in-place inflate and no-overwrite checks still apply. No new
project version or ROM format is introduced.

The user's exact exported mesh was normalized in memory: 1,439→1,531 vertices,
73→104 batches, 850 faces and 11 segments retained. Decoded bytes 37,280→38,544;
maximum batch 24 vertices. Geometry/corner data/collision and the source runtime
and in-place inflater checks pass. These checks do not substitute for the user's
gameplay verification. No emulator or test ROM is generated.

Regression coverage is in `tests/test_render_batches.py`: original-asset audit,
compiler boundaries, distinct vertex colors/identities, legacy v9/v10 project
round trips, export/history isolation, spatial seam collision, static references
and exact output budget accounting. Full-suite/native results are in STATUS.md.
