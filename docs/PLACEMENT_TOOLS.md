# Existing-object placement tools

Ctrl-click rows or viewport objects to select a group. The current
object is the primary object and transform pivot. Use Camera controls to choose
Perspective, Top, Front or Right, and Move, Rotate or Scale. A drag is one undo;
Escape, focus loss or changing view cancels it. Ctrl during a drag snaps.

Tools → Placement provides relative movement snapping, track surface snapping,
Drop to track below, height offset, alignment to the primary object, numeric
rotation/scale, copying and pasting the primary position, and applying decoded
property edits to all selected objects with the same stored field. Raw byte/bit
edits affect the primary object only. No operation creates entries.

Rotation/scale handles are enabled only for source-verified stored transforms:
Scenery yaw/radius, Door closed yaw/scale, WeaponBalloon scale, Animation XYZ
angles/scale, and Checkpoint yaw. Checkpoint path scale remains a property rather
than an artwork transform. Groups rotate about world Y; a single Animation can
also edit its stored X/Z angles. Sprite artwork continues to face the camera.
Rotation is quantized to the selected fields' native units. Group movement
clamps the common displacement at signed16 coordinate limits to retain spacing.

Surface tools raycast the rendered track triangles, including water and roofs.
Drop chooses the nearest surface below each origin; live snapping chooses the
highest surface. Isolating a segment also limits surface queries. Height offset
is relative to the object origin; these tools do not infer collision feet.

Verification: 564 headless tests pass; final rotation correction rechecked with
11 placement tests. Native Qt/OpenGL checks cover Ctrl selection, grouped moves,
undo/cancel, rotation rings, scale GPU reuse, copy/paste, alignment, grouped
properties, terrain drop and orthographic views. No sample ROM was generated;
gameplay testing is performed by the user.
