# About dialog ROM artwork — v1.25.4

The user's About dialog keeps its layout, text, styling, floating balloons,
click-to-pop interaction and FREEFORALL/ZAP/TT boost codes. Its game-themed
polygon/gradient illustrations are replaced by decoded game artwork.

Open a ROM, then choose **Help → About**. With no ROM loaded, the dialog shows
a text banner explaining how to enable the game artwork. There is no implicit
ROM search or bundled extraction. Missing/malformed artwork leaves a readable
fallback and logs the reason instead of preventing About from opening.

`src/core/about_artwork.py` loads images into memory. `src/ui/about_window.py`
converts them to owned QImages once and draws those cached images. Opening
About does not change project data or write PNGs/ROMs. The banner's animation
and rotation are UI presentation, not an emulation of the game's rendering.

## Verified asset references

| Artwork | Reference in the original Rev 1 ROM |
|---|---|
| Red/blue/yellow/green/rainbow balloons | `WeaponBalloon` header's sprite references, reordered from the game's boost/missile/trap/shield/magnet enum. Original sprites 148/147/150/149/151; their tiles include strings. |
| Golden balloon | `GoldenBalloon` header's first sprite reference, original 154. |
| Pop frames | Sprite 176, ten frames; manifest names this stored artwork `unused/weapon_balloon_pop`. |
| Diddy Kong Racing logo | Menu element IDs 0x50–0x5A, looked up through section18 `ASSET_MENU_ELEMENT_IDS`; texture mask0xC000, lower14 bits select 2D textures. The game's 15-pixel title-tile spacing also places its trademark. |
| Island/sea backdrop | 3D texture817, `objects/dome_blue_sky_island`, vertically flipped for the flat banner presentation. |
| Sun flare | 3D texture220, `objects/dome_sun_shining`; screen blended. |
| Zipper | GroundZipper header's shadow/decal reference, original 2D texture16. |

Sources: local `tools/dkr_assets_tool_extract.json`, `src/menu.h` menu texture
enum, `src/menu.c:646` title layout and `:13787` reference decoding,
`src/game_ui.h:9` masks, and existing object header/sprite/texture decoders.
Sprites are alpha-composited from their actual tile offsets. Pop frames share
one canvas origin so differently sized frames do not jump during playback.

## Interaction and lifecycle

Clicks use each balloon image's alpha, so empty corners do not pop it. A pop
plays the ROM frame sequence and respawns the balloon below the banner.
Magic codes retain the user's speed/zipper boost behavior. The timer starts
when the canvas is shown and stops when hidden. MainWindow schedules the
modal dialog for deletion after it returns, avoiding retained windows/timers
across repeated visits.

The source before this change is preserved locally as
`artifacts/about_window-user-original.py`. Other user source edits, original
ROMs, projects and running editor processes are untouched.

Verification: 61 initial artwork/ROM parser checks and 189 final focused
artwork/sprite/image/texture/edit-context checks pass. Native checks cover
no-ROM fallback, decoded images, alpha-aware popping and respawn, burst
lifetime, magic code, hidden timer and three Help/About open/close/deletion
cycles. Screenshots: `artifacts/about-rom.png`, `about-boost.png` and
`about-no-rom.png`; native harness: `artifacts/verify_about_native.py`.
