# Minimap settings

Open **Tools → Minimap** in the right inspector. Select a level, change settings,
and click **Apply minimap settings**. The preview shows drafts immediately;
Apply stores all changed settings as one undo step. Save the project and use
Save As ROM for your own game tests. **Export / replace map PNG**
shortcut opens its sprite in the image browser; see IMAGE_ASSETS.md.

Adventure 1/2 and Checkpoint overlay are preview controls and never dirty the
project. Cyan dots show existing checkpoint positions, with checkpoint 0 labeled;
the selected object is gold. These are alignment guides, not simulated racers.
Moving an existing object updates its preview marker. All checkpoint sets may
appear together; the overlay does not select a game's active racer/vehicle set.
The view fits the sprite and HUD anchor, so large marker offsets can move dots
outside the preview. Shared levels at the top use the same geometry/minimap.

## Verified fields

Offsets are relative to the complete inflated LevelModel entry. The header is
0x4C bytes; models are data section 27 with index section 26. Master LUT is
0xED0E0, asset base 0xED1B0 in USA Rev 1. Fields are big-endian.

| Offset | Format | Editor field / meaning |
|---|---|---|
|0x20|s32|Existing sprite index, replaced by a runtime pointer after loading|
|0x24|u16|Marker rotation in degrees; source converts with integer `(degrees * 65535) / 360`|
|0x26|u16|Unknown, protected|
|0x28, 0x2C|f32, f32|Marker X / Z scale multipliers; do not resize the image|
|0x30, 0x32|s16, s16|Adventure 1 marker X / Y offsets in HUD units|
|0x34, 0x36|s16, s16|Adventure 2 marker X / Y offsets in HUD units|
|0x38|u8|Unused high color byte, protected|
|0x39–0x3B|3 × u8|Map RGB tint, each 0–255|
|0x3C–0x47|6 × s16|Stored X/Y/Z bounds, protected|

Rotation keeps its unsigned16 storage range, including values above 359; the
consumer wraps the converted N64 angle. Scales accept finite float32 values;
zero collapses a marker coordinate and negative values reverse it. The text
fields show the shortest decimal that preserves the original float32 on no-op
Apply. Offsets accept the full signed16 range; positive Y is up on the HUD.

The reference list contains 189 existing sprites with nonempty first frames out
of 193 definitions. Empty first-frame definitions 162,172,175,177 are excluded
from new assignments. The game displays frame 0 for the minimap; other sprite
frames are not played. The tool changes only the reference, not its shared art
or anchor metadata. Choosing unrelated art does not automatically align it.

## Projection and preview

Local sources: `include/structs.h:737`, `src/game_ui.c:3295,3612–3669,3771–3799`,
`src/camera.c:1218` and `src/textures_sprites.c:1155,1306–1384`.
The image uses the sprite's texture tile positions and signed anchor. Its
vertices span `posX-anchorX` through `posX-anchorX+width-1`, and
`anchorY-posY-height` through `anchorY-posY-1`. No marker scale/rotation is
applied to this image. Adventure 2 reflects it horizontally, then shifts its
origin left by anchorX, matching the HUD's yaw and origin adjustment.

For bounds spans `A=upperX-lowerX`, `B=upperZ-lowerZ`, source marker projection is:

```text
sx = 60 * (A/B) * scaleX * (X-lowerX) / A
sy = -60 * scaleY * (Z-lowerZ) / B
rx = sx*cos(angle) + sy*sin(angle)
ry = sx*sin(angle) - sy*cos(angle)

Adventure 1: (rx+offset1X-anchorX, offset1Y-ry+anchorY)
Adventure 2: (-rx+offset2X-anchorX, offset2Y-ry+anchorY)
```

These coordinates are relative to the HUD minimap origin, with positive Y up.
The preview follows the source's integer degree conversion and uses continuous
trigonometry instead of the game's integer sine table; subpixel differences are
possible. It is an enlarged alignment preview. It excludes NTSC/PAL screen
layout, HUD motion/fade, multiplayer placement, camera roll and live racer state.
Tint is shown at full opacity. The game caps the map opacity at 160 and forces
white map tint with three active players; changing tint may therefore be invisible
in that mode. Some hubs/cinematics do not display a map in their usual game state.

## Persistence and protection

Minimap, material, header, object and research edits share history and project
saves. **Revert minimap to original ROM** restores only the fields above;
material changes survive. Reverting materials likewise preserves minimap changes.
Version 5 projects enable the combined material/minimap whitelist. Versions 1–4
remain readable; version 4 model overlays retain their material-only validation.
Unknown color bits, offsets, counts, geometry, collision, BSP and inflated tails
stay protected. No object or asset is added, removed or resized structurally.

The exporter recompresses changed models, rebuilds their table/master offsets,
reports shared uses and field changes, retains untouched compressed entries,
updates N64 checksums, and enforces the existing original-ROM padding budget.
Minimap-only refreshes do not rebuild the 3D mesh or alter camera speed/framing.

Headless tests cover every field, all 55 no-op models, references, finite/range
validation, projection orientation/units, protected bytes, independent reverts,
old/new project validation, mixed material/header overlays, in-memory export,
checksums and unchanged assets. Native checks cover drafts, applying, history,
sprite changes, mirrored views, selection/movement, project reopening and GL.
User game validation remains separate: compare marker placement against the map
on a track in Adventure 1 and mirrored Adventure 2, and test tint in a supported
player mode. No sample ROMs are generated for review.
