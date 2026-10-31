# Course Builder — v1.25.0

Open **Edit → Course Builder…** with a level loaded. The existing
**Tools → Routes → Course builder…** button opens the same independent window.
It uses the current track geometry and artwork, including imported OBJ tracks.
Everything stays in a draft until **Apply course**; Cancel leaves the project
unchanged. Cleanup, routes and starts become **one project undo step** together.

## Start a new course on imported geometry

1. Click **Start fresh — clear all objects**. This stages removal of every placed
   object in both loaded maps: scenery, pickups, cameras/actors, checkpoint sets,
   alternates, starts and other helpers. Geometry, collision, textures and level
   settings remain in place. The preview clears immediately and switches to Top.
   Use **Replace race setup — keep other objects** to remove checkpoints, starts
   and AI nodes while retaining the other placed objects. **Cleanup** also offers
   category checkboxes, counts and a shared-map affected-level notice.
2. Use **Place checkpoints**, then click along the road in driving order. The
   first point is orange **CP0**; the loop closes automatically. Draw at least
   four main points. New points get tangent headings, neutral HUD/behavior values
   and even AI lanes. Fresh setup also enables **Copy this route to every level
   vehicle set**: the builder creates a separate copy for each set referenced by
   Car/Hovercraft/Plane, retaining the level header's existing mappings. This
   prevents another vehicle from retaining the old track's route.
3. On **Start grid**, click **Place grid on road, then aim it**. First click the
   road at the center of the front row, then click ahead in the intended driving
   direction. All eight numbered racer positions update immediately. Labels are
   green when placement succeeds and red when surface snapping fails. **Aim grid
   toward road point**, **Rotate grid 180°**, heading and spacing controls update
   the whole grid. **Focus grid** zooms to the complete layout.
4. Put the entire grid on the approach from the last checkpoint toward CP0.
   **Fit whole grid on approach before CP0** walks back along that approach and
   checks all eight positions. **Minimum distance before CP0** controls clearance;
   the helper may move farther back to fit. It refuses when a straight grid does
   not fit; reduce spacing or place it manually. Inspect the road and barriers.
5. Read **Readiness**, then **Apply course**. Apply runs exact ROM/capacity and
   reference checks automatically. **Review changes / ROM budget** runs those
   checks without applying. Save a project and export your ROM normally for
   testing. No emulator or review ROM is generated automatically.

An empty draft is editable and shows missing-route/start diagnostics. A fresh
race is not reported as ready until its requested route and grid can be built.
The Apply checkboxes let you work on only the route, only the grid or cleanup.
Binary/reference/capacity checks still apply to the final candidate transaction.

## Moving and editing the draft

Hold **middle mouse and drag** to pan in any view, including while a placement
tool is selected. Release to stop; Escape/focus loss releases mouse capture.
Checkpoint arrows show driving direction (v1.25.2), opposite the mathematical
plane normal. The displayed direction does not change saved checkpoint angles.

Choose **Select / drag**, then select a numbered marker. A checkpoint can be
dragged with the existing axis/center handles; dragging any numbered start moves
the whole grid. Point/table selection stays synchronized. Point drags snap to
nearby road by default; the Y handle allows deliberate height changes. A failed
snap retains the prior point and reports why. Esc or focus loss cancels a drag.

**Undo draft / Redo draft** (Ctrl+Z, Ctrl+Y/Ctrl+Shift+Z) undo draft placement,
cleanup, point order/coordinates, grid settings and completed drag gestures.
They do not touch project history. After Apply, use the main editor's Undo to
restore the whole prior scene. Closing the builder discards the draft.

Use **Up/Down**, **Insert midpoint**, **Remove**, **Make CP0** and **Reverse
(keep CP0)** to edit route order. Double-click XYZ cells to type coordinates;
double-click a checkpoint number to focus it. Switching stored sets retains
their drafts. While copying one common route to every vehicle set, switching
sets shows that common route with fresh identities for the new target set.

Opening an unchanged course does not renumber it. Category-only cleanup and
grid-only edits retain untouched checkpoint records exactly. Requested route
edits renumber its main rows from 0. An existing route's headings, lane values,
HUD cues and unknown bytes stay stored unless explicitly reset. Advanced
checkpoint controls expose the new-entry map, lane scale/width, retained lane
reset, alternate removal and the original downward-only batch-drop operation.
The map selector affects new entries; retained objects stay in their maps.

Retained alternates follow the new index of their paired retained main. Removing
a main with an alternate is refused unless alternate removal is selected.
Copying a common route explicitly replaces the other mapped sets, including
their alternates, with neutral-lane copies. The runtime bound remains **60
entries per selected set including alternates**, separate from map/RAM/ROM bounds.
Other object references and special behavior are not repaired automatically.

## Starts, surfaces and diagnostics

Starts are numbered **1..8** in the preview; their stored racer indexes remain
0..7. The front-row center is the anchor. Two columns, column spacing 120 and row
spacing 140 are defaults, not game constants. Heading snaps to **5.625°**.
Advanced entrance/vehicle controls retain support for other entrance IDs, odd-
column stagger and overrides. Ancient Lake's stock race uses **entrance 0**.
Editing another entrance does not replace entrance 0. Duplicate/invalid existing
indexes in the target entrance must be resolved or cleared before rebuilding.

**Snap each racer to nearby road** searches above and below the anchor and uses
the local clicked-layer slope to predict each position's height. It chooses the
nearest surface layer within 512 units of that prediction; equidistant distinct
layers are refused. This handles hills without picking a distant roof by default.
Height above road is applied after the hit. Clicking uses rendered triangles,
including roofs/water, and excludes hidden collision guides. This is placement
assistance, not a simulation of game collision, vehicle clearance or drivability.

Readiness reports missing/short courses, absent/incomplete racer grids, duplicate
indexes, orphan alternates, missing AI links, nearly parallel crossing planes,
missing rendered floors, conflicting vehicle overrides, starts on/beyond CP0 and
starts facing away from the approach. Warnings can refer to retained stock data
or another entrance. Double-click an object-linked issue to focus it. Passing
checks does not prove AI, lap, camera or gameplay behavior; the user tests those.

The builder's arrows all show **driving direction**. CP0 also has a crossing-gate
outline. Main-viewport checkpoint arrows retain their original plane-normal
convention; no ROM heading convention has changed.

## Source and persistence

Authoritative local checkout: `research/Diddy-Kong-Racing`.

- `include/level_object_entries.h:119–157`: SetupPoint is **12 bytes**, with
  racerIndex/entranceID/angleY/vehicle at hex offsets 08/09/0A/0B. Checkpoint is
  **28 bytes**, with scale/index/yaw at 08/09/0A, four lateral bytes B..E, heights
  F..12, behaviors 13..16, alternate 17, unused 18, HUD cue 19, set 1A, unused 1B.
- `include/object_functions.h:12`, `src/object_functions.c:2484/3194`: stored
  yaw shifts by 10; checkpoint scale is `max(scale,5)/32`. Lanes use signed8
  offsets. XYZ remains signed16; lane quantization bounds are enforced.
- `src/objects.c:5530–5800`: collects up to 60 selected-set checkpoints, sorts
  main indexes/alternate index+255 and pairs by index. Sparse stock indexes are
  valid. Runtime crossing-plane normal is `(sin(yaw),0,cos(yaw))`.
- `src/objects.c:1059–1145/1281+`, `src/racer.c:2977–2979/3158+`: setup points
  match entrance/racer index; the last matching vehicle override wins. Racer
  forward is local negative Z: `(-sin(yaw),0,-cos(yaw))`.

The refresh uses existing structural map/identity writers and project version15;
older project versions retain their prior permissions. It adds no binary fields,
new object IDs, header remapping or project schema. Full Review/Apply checks
include shared-map references, runtime/workspace/in-place-inflate bounds, exact
compression/ROM budgets and stale-plan rejection. Untouched entries/assets stay
unchanged. Fresh copies satisfy existing vehicle-to-set mappings in the same
transaction instead of temporarily deleting referenced custom sets.

Automated/native results are recorded in compact STATUS.md. Autosave, recovery
and backups remain deferred; further milestones require user authorization.
