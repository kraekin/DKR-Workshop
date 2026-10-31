# Existing routes and parameter fields

Use **Tools → Routes** in the inspector. The list labels each existing checkpoint
with index, set, main/alternate status, vehicle mapping and original map/entry
identity. AI nodes show IDs and four outgoing slots. Double-click to focus.

## Checkpoint lane handles

Select a checkpoint and enable **Drag lane points in viewport**. Numbered points
0–3 are the four AI lanes, independent of vehicle choice. Click/drag a point or
choose the active lane in the panel, then use its movement arrows. Top/Front
views help separate sideways and height changes. Ctrl during a drag snaps to
the configured world movement step. Numeric lateral/height/behavior fields are
also provided. Raw property editing remains available in Objects.

The source layout is `LevelObjectEntry_Checkpoint`, 0x1C bytes:
lateral fields `unkB..unkE` at 0x0B..0x0E, vertical `unkF..unk12` at 0x0F..0x12
and behavior `unk13..unk16` at 0x13..0x16, each signed8. With
`S=max(scale,5)/32`, lane target is
`(X+S*cos(yaw)*lateral, Y+S*vertical, Z-S*sin(yaw)*lateral)`.
Dragging projects onto that lateral/vertical plane, rounds/clamps to signed8,
then displays the actual stored result. It does not move the checkpoint origin,
change longitudinal offsets, behavior or other lanes. Derived points retain
subunit precision and can extend beyond the signed16 origin-coordinate range.

Each drag is one undo operation; Escape, focus loss or changing view/mode cancels
it. This tool edits existing nodes only. Index/set/alternate parameters can still
be edited through the original decoded properties; references are never silently
renumbered. Lane paths are previews of source control points, not simulations
of vehicle collision, steering decisions or game state.

See [CHECKPOINT_FIELDS.md](CHECKPOINT_FIELDS.md) for source consumers, lane
behavior selectors, HUD course cues and the user's confirmed HUD cue experiment.

## AI directed connections and diagnostics

For the current source-backed explanation of graph consumers, destination
tags, elevation and practical setup, see [AI nodes](AI_NODES.md). In particular,
`unk8` is used by challenge destination searches; the older Phase13 scope
below did not yet assign it a meaning.

`LevelObjectEntry_AiNode` is 0x10 bytes. Node ID is u8 at 0x09, four u8 target
slots at 0x0A..0x0D, signed elevation at 0x0E and trailing byte at 0x0F.
The runtime uses one global table of 128 nodes for all loaded maps. IDs 0..127
are fixed; 255 requests runtime assignment. Target 255 means no connection.
The source uses the low two elevation bits for its elevation groups; no meaning
is assigned here to the remaining bits or `unk8`/padding.

Choose a target for an existing slot or press **Pick…**, then click an existing
AI node marker. Escape cancels picking. Links are directed: editing A → B does
not edit B → A. A new link must identify one loaded target and cannot create a
self/repeated target. Choose **255 · No connection** to clear a slot. Other slots
and raw data are retained even when they contain unusual values. Raw experiments
remain possible in the Objects properties.

Diagnostics report duplicate checkpoint index/set/alternate identities, orphan
alternates, missing header-selected sets, the 60-checkpoint runtime capacity,
main255/alternate0 sort-ID collisions, duplicate AI IDs, runtime-assigned IDs,
invalid/dangling/ambiguous/self/repeated connections. Skipped checkpoint indexes
are allowed and shown as information: the game sorts stored indexes. Nothing
is repaired automatically. Ambiguous AI nodes are omitted from the line preview
instead of silently selecting one duplicate. Existing diagnostics do not prove
a level cannot run, nor validate every game-state-dependent route behavior.

Authoritative local sources inspected: `include/level_object_entries.h:131`,
`src/object_functions.c:3194`/`:4183`, `src/objects.c:45`/`:50`/`:5530`/`:7347`
and `src/racer.c:9060`, all under `research/Diddy-Kong-Racing`.

## Parameter descriptions and project notes

The Objects inspector shows descriptive field names with source keys and units
in tooltips. See [Verified parameter labels](PARAMETER_LABELS.md) for the current
mapping and [Checkpoint fields](CHECKPOINT_FIELDS.md) for lane behavior details.
Unresolved fields remain explicitly unknown; lack of a visible change does not
establish that a byte is unused.

The former notes panel is retired. Existing project note records and labels
remain compatible and survive saves; they never enter ROM assets. The serialized
keys remain unchanged so older project overlays can still be read.
