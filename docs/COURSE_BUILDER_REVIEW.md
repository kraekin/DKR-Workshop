# Course Builder usability review — 2026-10-21

The authorized v1.25.0 refresh implements this review's recommendations; see
[the updated Course Builder instructions](COURSE_BUILDING.md). The observations
below describe the v1.24.4 baseline and are retained as review evidence.

Review of v1.24.4 after importing the Blender starter tracks. This is a proposal;
application behavior, project format and ROM writers have not been changed.

## What the current workflow gets wrong

The builder is effective at rearranging an existing course, but it opens as an
existing-course editor even when the geometry has been completely replaced.
It asks users to manage stored sets, maps, entrances and a separate preview
operation before they can see a believable new race layout.

Confirmed with source review and an isolated Qt dialog/core check:

| Current behavior | Consequence |
|---|---|
| Geometry import retains all placed objects in both loaded maps. | The original course's scenery, starts, cameras, routes and pickups remain around the new mesh. |
| Clear draft empties only the selected set's main-checkpoint rows. | It is not a level-object cleanup tool. In stock Ancient Lake, clearing its 18 set-0 main rows still leaves 166 objects in the draft preview, including the other checkpoint set. |
| An empty route cannot build while Apply checkpoint sequence is checked. | Clear draft followed by Build produces the 4..60-point error rather than a useful fresh-course state. |
| The start-grid checkbox begins unchecked and its anchor is loaded from the stock course. | A new course opens with an irrelevant old anchor; entering numbers alone need not enable grid editing. |
| Clicking a grid anchor does not update the eight start markers until Build course preview. | Placement gives no immediate visible answer. Changing grid spacing after a successful build restores the original markers until the next build. |
| Grid placement only casts downward from one common anchor height. | Road that rises above that height is missed. On Gentle Hills, 14 of 16 guide-based road-anchor samples failed using the default grid layout, even though the road was present. The same check passed at all 16 sampled anchors on each flat starter track. |
| Position grid before checkpoint 0 uses a fixed 200-unit offset along the inferred heading. | It does not follow the approach road, adapt to grid length or establish that all eight positions fit the road. |
| Entrance is an unlabeled numeric ID; the selected ID is not inferred from how the game enters the course. | A perfectly valid new grid for another entrance can leave the normal race starts unchanged. Ancient Lake's existing race grid uses entrance 0. |
| Diagnostics check existing groups/entrances, but neither exists in an empty object list. | A completely empty list currently produces no course diagnostics. Existing checks also do not establish that every start is before CP0 and facing the intended direction. |

Additional code-review findings: changing checkpoint sets reloads that set and
discards the previous unsaved point draft; there is no builder-level undo for
point insertion/removal/reversal; marker selection is reset during draft refresh.
The builder does not connect viewport object-movement signals back to its point
table. Its click-to-move mode works, but is a separate tool from normal object
dragging. Checkpoint markers show crossing-plane normals while start arrows show
racer forward, which makes their opposite arrow conventions confusing here.

## Recommended workflow

**Choose a starting point → Place the route → Place the starting grid → Review.**
Keep this in the existing independent window. Offer a direct menu entry so users
do not need to discover it under the right pane's route tools.

### 1. Start fresh and bulk cleanup — first priority

Offer **Edit existing course** and **Start fresh on this geometry** when opening.
An optional link after geometry import can open the same workflow.

Start fresh should offer **Clear all placed objects** and category choices:
checkpoints/alternates, race starts, scenery, pickups/zippers, AI nodes,
cameras/animation actors and other gameplay objects. Show removal counts across
both loaded maps. Do not force users to delete points individually or leave an
unseen alternate/set behind. Include a simple option to retain scenery while
rebuilding only the racing setup.

Clear the selected objects immediately in the builder's draft view. Retain the
imported geometry, collision, artwork and level settings. Stage cleanup and new
checkpoints/starts together, then Apply as one undoable transaction. This avoids
making users temporarily break edited checkpoint-set references while rebuilding.
Show other affected levels when a map is shared. Empty drafts must be editable
without being described as ready to race.

### 2. Visual start-grid placement — first priority

Use **Place starting grid**: click the road for the front-row center, then click
or drag toward the intended driving direction. Display all eight numbered racer
positions and one prominent driving arrow immediately, including while spacing
and heading change. Allow moving/rotating the entire grid as a group.

Use a labeled normal race entrance by default where established; put other
entrances, vehicle overrides and numeric angle controls under Advanced. State
whether this operation replaces an existing grid or creates a new entrance.
Keep the game's 5.625-degree heading quantization, but show the actual snapped
result rather than requiring users to reason in stored angle bytes.

Fix the terrain search so each racer can snap to a nearby road height above or
below the clicked anchor. Prefer the clicked surface layer and report ambiguous
bridges/roofs rather than blindly selecting the highest surface in the level.
Invalid positions should remain visible in red, with a reason beside them.

Replace the fixed-distance helper with an adjustable **Place behind CP0**
preview that accounts for the whole grid and checks its footprint on the road.
It should remain adjustable; a curved or narrow approach may need manual placement.

### 3. Route editing that behaves like the main viewport

Default a fresh course to top view. Use clear Place/Select/Move controls, numbered
checkpoints, a distinct CP0 crossing plane and consistent driving-direction
arrows. Synchronize list selection and viewport selection; allow dragging points
with surface snapping, inserting between points and choosing a different CP0.

Add draft Undo/Redo for point operations, grid placement and cleanup choices.
Preserve drafts when switching tabs/sets, or explicitly offer to discard them.
For a new route, align headings and initialize neutral AI lanes by default.
Keep stored map/set IDs, alternate routes and special lane behavior in Advanced.
Expose which vehicles use the authored route without requiring a separate trip
to Level Settings for ordinary new-course setup.

### 4. Continuous preview and useful readiness checks

Update lightweight points/grid/lanes immediately. Run expensive compression and
ROM preflight at Review/Apply, with a separate budget refresh if wanted. Keep
Apply unavailable for stale/invalid plans, but do not erase the visual draft or
replace it with stock markers when a field changes or one point is invalid.

Show clear statuses for: route present, selected vehicle mappings valid, ordered
checkpoints, eight unique starts in the intended entrance, every start before
CP0, forward direction toward CP0, surface placement and remaining stock objects
outside the new course. Offer focus links and specific actions such as Rotate
grid 180 degrees or Move grid farther back when applicable. Distinguish errors,
warnings and information. A successful static check is not gameplay validation.

## Current workaround for placing starts

In Start grid, enable **Apply eight-racer start grid**, use the existing race
entrance (0 for Ancient Lake), and place the anchor on the new road. Set the
heading, then Build course preview and inspect all eight arrows before Apply.
For a grid-only change, uncheck Apply checkpoint sequence so an empty/unfinished
route draft does not block it. On slopes, temporarily raise anchor Y above the
road under the whole grid while Drop starts to surface below remains enabled;
inspect for overhead surfaces. The height offset alone does not fix the search,
because it is applied after a successful terrain hit.

## Evidence and scope

Reviewed src/ui/course_builder.py, src/core/course.py, route/terrain/structural
writers, the existing tests and docs. Cross-checked SetupPoint and checkpoint
layouts/init/spawn selection against the local include/level_object_entries.h,
src/object_functions.c and src/objects.c. SetupPoint remains 12 bytes and a
checkpoint 28 bytes; no binary-format changes are proposed.

Reproduction: artifacts/review_course_builder_usability.py, with recorded results
in artifacts/course-builder-usability-evidence.json. These checks exercise
isolated Qt state and headless compiled geometry; no emulator playtest or new
OpenGL regression claim is made. No application code, user session, sample
track, source ROM or project was changed. No test ROM was written.

Recommended implementation order: **cleanup + visible, reliable starts**, then
**route manipulation + continuous preview/readiness**. All remain proposals
until the user selects implementation.
