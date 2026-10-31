# Texture and sprite PNG workflow

Open **Edit → Texture & Sprite Browser / PNG** (bottom of Edit, after the separator). Browse 1,416 3D textures,
916 2D textures and 193 sprite definitions with thumbnails, ID/format/dimension
filters, frame selection and known shared uses. Materials and Minimap also
provide direct **Export / replace … PNG** shortcuts.

Track import also supports dedicated static textures appended by
OBJ/MTL/PNG import. They appear after the stock1,416 3D assets and can use the
same fixed-layout pixel/timing workflow. See
[CUSTOM_TRACK_ARTWORK.md](CUSTOM_TRACK_ARTWORK.md) for creation and format/size
choices during track import; those changes are not stock image-header edits.

## Export, edit, reimport

1. Select an existing asset/frame and **Export stored frame PNG**. This exports
   untinted RGBA pixels without modifying the project or ROM.
2. Edit externally, retaining dimensions and tile layout. Export/import each
   existing frame separately; format, frame count and palettes stay fixed.
3. **Import frame PNG** stages a preview. Compare Stored, Imported PNG and
   N64 result; the latter shows the actual encoded/decoded pixels and reports
   quantization differences. No edit is stored yet.
4. **Apply imported frame** commits one undo step, including every tile in a
   multi-tile frame. Save the project and export a new ROM for your game test.

**Discard import preview** restores the stored view. Export always uses the
stored frame; Apply first to export the edited result. An unchanged export/reimport
does not dirty the project or recompress its original asset. Imports accept one
PNG frame, converted to RGBA, and reject APNGs, other formats and wrong sizes.
No crop or resize occurs.

**PNG orientation → Automatic** follows the local extractor: ROM 3D textures
are flipped vertically for thumbnails, previews and exported PNGs, and flipped
back automatically on import. This makes the Fossil Canyon sign (texture186)
upright while retaining its original stored rows and UVs in the game. Extracted
Texture JSON uses its explicit `flipped-image` convention, including no-flip
exceptions. 2D textures and sprite canvases keep their existing orientation.
Dedicated custom images keep their authoring PNG's rows in Automatic mode;
the stock extractor flip is not applied to them.
Orientation controls affect the PNG workflow only; they never dirty a project
or change renderer/OBJ coordinates or saved bytes by themselves.

New browser exports include PNG text fields `dkr-asset-section` and
`dkr-png-rows` (`flip-y` or `stored`). Import honors these for the same asset
section, preventing a second flip even if the selector has changed. An external
editor can strip this metadata: Automatic still imports ordinary upright 3D PNGs
correctly. For untagged raw PNGs exported by v1.9.0, select **Raw ROM rows
(legacy PNGs)** before import. This also offers a raw preview/export when useful.
Switching orientation after staging an import changes its view, not the decoded
draft's stored row placement. Apply and undo retain their existing behavior.

The decomp's `extractTexture.cpp:31–42/52–53`, extract config defaults and
`buildTexture.cpp:112–114` establish this reversible flip. Stored texture186 is
vertically inverted; geometry13 slot11 maps V32 to upper sign vertices and V0
to lower vertices. Its UVs require no change.

Nonoverlapping sprite tiles export as an assembled pixel canvas. Overlapping
tiles use a labeled tile sheet arranged left to right so even hidden texels can
be edited. This interchange layout does not change the game sprite's layout.
Keep transparent gaps outside tiles unchanged. Imports split into the same tile
IDs. Anchors do not change PNG dimensions/layout. Empty frames have no image.

## Format conversion and metadata

| Format | Import conversion |
|---|---|
|RGBA32|All four 8-bit channels retained|
|RGBA16|RGB uses integer `(channel+4)*31/255`; alpha 0 is transparent, any nonzero alpha becomes opaque|
|IA16|Intensity `(R+G+B+1)/3`; 8-bit alpha|
|IA8|Intensity and alpha use four bits each, divided by 17|
|IA4|Three-bit intensity via division by 36; zero/nonzero alpha|
|I8 / I4|Grayscale intensity; stored alpha is unavailable|
|CI4 / CI8|Codec tests use an existing fixed palette. Original Rev 1 has no CI images or palette bytes; palette writing remains disabled.|

IA/I formats cannot store independent RGB colors. Ancient Lake's minimap uses
intensity/alpha; the minimap's tint controls its final color. Browser artwork is
untinted; game material/prim colors and effects can further change its appearance.
Odd-row swaps are reapplied using four-byte halves, or eight-byte halves for
RGBA32. Headers, unknown padding, unused nibbles and unchanged pixel encodings
are preserved. Only changed texels are patched.

Sprite anchors are signed16 X/Y at 0x04/0x06 in the 12-byte SpriteAsset header.
**Apply anchor** affects all users. Base texture, count, frame offsets at0x0C,
unused word at0x08 and tails remain protected. Sprite definitions have no speed
field; that comes from object/behavior data.

Texture `frameAdvanceDelay` at0x14 is unsigned16 advance per 60 Hz update in a
256-units-per-frame counter: larger values advance faster, zero pauses. Game
flags decide whether it is used. **Apply timing** updates existing frame headers
and the compressed outer header together; no-ops preserve legacy metadata.
The browser selects frames manually. Animated track/environment simulation
remains separately scoped.

Local sources: `include/structs.h:102–170`,
`src/textures_sprites.c:970–1048,1306–1384,1620–1684`,
`tools/dkr_assets_tool_src/builder/buildTypes/buildTexture.cpp`, `buildSprite.cpp`,
`helpers/imageHelper.cpp:191` and `libs/n64graphics/n64graphics.c:16,207–317,506–566`.

## Shared uses, projects and export

Edits are global to existing texture IDs. Known dependencies include track
slots, object models/headers, placed animation targets, sprites and minimaps,
propagated to referencing levels. Compiled HUD/menu references and dynamic spawns
can add uses; the browser/report explicitly label the list as known uses.
No listed level reference does not establish that an image is unused.

Version6 projects read versions1–5. Texture sections2/4 use `texture-decoded`
overlays: compressed canonical bytes are the original 0x20-byte outer header plus
the entire inflated entry; uncompressed entries retain raw bytes. Hashes/offsets
refer to these bytes, including decoded tails. Sprite section12 uses raw anchor
overlays. Older versions cannot opt into these writers. Multi-tile imports share
one grouped history operation while storing ordinary per-texture overlays.

The writer rebuilds tables3/5/13 and master offsets, retains untouched compressed
entries and table/section tails, aligns changed compressed entries and updates
N64 checksums. Decoded sizes, IDs and counts remain unchanged. Compressed growth
uses only original-ROM padding; preflight refuses over-capacity output. ROM
expansion, new dimensions/formats/palettes and longer sequences remain deferred.

**Revert asset artwork to original ROM** restores a texture's pixels/timing.
For sprites it restores the anchor and all referenced 2D tiles across all frames;
shared users of those tiles also revert, as one undo step. Object, level, material
and minimap settings survive. The source ROM stays read-only. Decomp assets
support inspection/PNG export; editing requires the verified original ROM.

Headless checks cover stock no-ops, every sprite frame's layout, quantization,
alpha/swaps, protected bytes, grouped history, projects, in-memory ROM reload,
unchanged assets/checksums, shared references and capacity refusal. Native checks
read edited track/sprite texels back from the GPU and exercise PNG round trips,
minimap artwork, anchors, timing, history and project reopening without GL errors.
In-game tests remain with the user; no sample ROMs or emulator runs are made.
