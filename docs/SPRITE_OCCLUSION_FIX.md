# Scenery sprite/wall preview correction — v1.25.3

Looking down at Central Area's snow doorway could cut off the tops of both
RubberSnowTree sprites. Native reproduction at camera XYZ=(-3575,804.4,-2529.7)
showed the flat cards tilting into the cliff as the viewing pitch changed.
The opaque wall's depth test then correctly covered the intersecting parts.

Scenery sprites now stand upright in Perspective view and turn horizontally
toward the camera's position. Their orientation stays stable when looking
around from the same position. Trees, bushes, flowers, reeds, lampposts and
snowmen use this preview convention through their existing BHV_SCENERY behavior;
it is independent of artwork IDs. Collectibles and animated sprite actors keep
their screen-facing presentation. Orthographic views retain screen-facing
cards so sprites remain visible and selectable from Top view.

The renderer and alpha-aware picker use the same basis and fallback at a
camera directly above the anchor. Mixed scenery/regular uses of one texture
retain separate draw ranges. Animated/hidden frames and live position/scale
updates retain their existing filters and cache handling. Depth testing and
alpha cutouts remain active; walls still hide scenery placed behind them.
Partly transparent upright tiles sort by their displayed centers, accounting
for the height of the card in the camera's depth direction.

This is an editor preview choice. The local `include/f3ddkr.h:10–45`,
`src/camera.c:1146–1176` and `src/textures_sprites.c:1306` describe the game's
screen-aligned anchor billboards and tile extents. The new upright marker is
derived preview metadata, with no serialized flag or project version change.
Original pixels, dimensions, anchors, placement bytes and ROM exports are
unchanged. No re-export is needed to use the corrected editor preview.

Native framebuffer checks at the reported doorway retain 100% of the sampled
interior tree pixels, versus 43.7% with the old orientation. Independent opaque
wall checks at three pitches verify that a front card remains visible and a
rear card is fully hidden. Headless tests cover orientation stability, vertical
fallback, loader scope, alpha-aware picking and orthographic behavior.
The native follow-up also checks blended foliage through the shared transparent
pass; final focused tests cover the displayed-center sort calculation.
Evidence: `tests/test_sprite_billboards.py`, `artifacts/sprite-billboards-*.txt`
and `artifacts/verify_sprite_billboards_native.py`. Final gates are in STATUS.md.
