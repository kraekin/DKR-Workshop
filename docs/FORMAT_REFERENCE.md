# Local decomp format reference (Phase 0 verified 2026-10-19)

## Verified target and asset tables

Root ROM: `Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64`, 0xC00000 bytes,
BE magic 80371240, cartridge NDYE, revision byte 1, SHA-1
`6d96743d46f8c0cd0edb0ec5600b003c89b93755` = USA 1.1 / `us.v80`.
Source: extraction config `inputs-supported`, `ver/splat/dkr.us.v80.yaml:450`,
`ver/symbols/undefined_syms.txt:11`, and direct read-only ROM inspection.

`__ASSETS_LUT_START=0x0ED0E0`, `__ASSETS_LUT_END=0x0ED1B0` (0xD0 bytes).
BE u32 word 0 is 50 sections; words 1..51 are 50 relative starts + final end.
Section i starts at `0x0ED1B0 + word[i+1]`, size `word[i+2]-word[i+1]`.
Logical asset end is 0xB8CFD0. Source: `src/asset_loading.c:43-81` and config
`sections` order. The following absolute ROM ranges are end-exclusive:

| Section | Table index / ROM range | Data index / ROM range | Entries |
| --- | --- | --- | --- |
| TEXTURES_3D | 3 / 29A270–29B8A0 | 2 / 0ED2D0–29A270 | 1416 |
| TEXTURES_2D | 5 / 37E7B0–37F610 | 4 / 29B8A0–37E7B0 | 916 |
| SPRITES | 13 / 38D500–38D810 | 12 / 38C640–38D500 | 193 |
| LEVEL_OBJECT_MAPS | 20 / 38F750–38F980 | 21 / 38F980–3AD050 | 138 |
| LEVEL_HEADERS | 22 / 3AD050–3AD160 | 23 / 3AD160–3B0430 | 65 |
| LEVEL_NAMES | 24 / 3B0430–3B0540 | 25 / 3B0540–3B1210 | 65 |
| LEVEL_MODELS | 26 / 3B1210–3B1300 | 27 / 3B1300–55B0A0 | 55 |
| OBJECTS (object headers) | 33 / 6CBC40–6CC110 | 34 / 6CC110–6D79D0 | 304 |

Names above have `ASSET_` prefix; tables have `_TABLE` suffix, except the object
table is `ASSET_OBJECT_HEADERS_TABLE`, and its data is `ASSET_OBJECTS`.
Subtables contain BE u32 data-relative offsets, one terminal end offset, then
FFFFFFFF; trailing alignment is not another entry. Adjacent offsets give size.
Source: `tools/dkr_assets_tool_src/extract/assetTable.cpp:88` and game loaders.
USA 1.0 / `us.v77` uses LUT ECB60–ECC30; do not apply those offsets to Rev 1.

## Verified layouts (hex offsets, N64 32-bit pointers, BE unless stated)

Authoritative C: `include/structs.h:102,430,574,599,618,693,737`.
`ptr` below is a 4-byte field, not the host Python pointer size. Unknowns are
kept unknown; grouped comma-separated fields occupy successive offsets.

**LevelHeader: C size C4 (196), ROM record C8 (200).** The tool's serialized
definition adds a u32 at C4 (`fileTypes/levelHeader.hpp`); observed table stride
is C8. `src/game.c:378-390` loads by table span, not a hardcoded C4 stride.

```text
00 s8 world; 01 u8 unk1; 02,03 s8 unk2,unk3; 04 s8 unk4[4]
08 f32 course_height; 0C u8 unkC[10]; 16 u8 unk16[10]
20 ptr AILevelTable; 24 u8 pad24[6]; 2A s8 unk2A[10]
34,36,38 s16 geometry,collectables,skybox
3A,3C,3E,40,42 s16 fogNear,fogFar,fogR,fogG,fogB; 44 u8 unk44[5]
49..4E s8 skyDome,playerIndex,laps,race_type,vehicle,available_vehicles
4F s8 unk4F[3]; 52,53 u8 music,unk53; 54 u16 instruments
56..59 u8 waveSubdivisons,unk57,waveSineStep0,waveSineBase0
5A s16 waveSineHeight0; 5C,5D u8 waveSineStep1,waveSineBase1
5E,60,62,64,66,68 s16 waveSineHeight1,waveSeedSize,wavePower,unk64,unk66,waveTexID
6A,6B u8 waveUVScaleX,waveUVScaleY; 6C,6D s8 waveUVScrollX,waveUVScrollY
6E s16 waveViewDist; 70 union ptr unk70 / u8 wavesXlu,waveDoubleDensity + padding
74 ptr unk74[7]; 90,92 s16 weatherEnable,weatherType; 94,95 u8 intensity,opacity
96,98,9A s16 weatherVelX,Y,Z; 9C s8 cameraFOV; 9D u8 bgColorRGB[3]
A0,A1 u8 unkA0,unkA1; A2,A3 s8 unkA2,unkA3; A4 ptr unkA4 (sky texture ID in ROM)
A8,AA s16 unkA8,unkAA; AC ptr pulseLightData (misc ID in ROM); B0 s16 unkB0
B2,B3 u8 unkB2,voiceLimit; B4 u8 voidColourRGB[3]; B7 u8 useVoid
B8 s8 bossRaceID; B9 u8 unkB9; BA s16 unkBA (second object map); BC u8 unkBC
BD s8 unkBD; BE u8 BGColourBottomRGB[3]; C1 u8 BGColourTopRGB[3]; C4 u32 ROM tail
```

The ROM's 20..29 is two inline 5-byte AI tables, not an address to dereference
(`src/game.c:460,705`, tool header). Fields 74..8F are signed misc asset IDs.

**LevelModel: 4C (76)**; **LevelModelSegment: 44 (68)**:

```text
Model: 00 ptr textures; 04 ptr segments; 08 ptr segmentsBoundingBoxes
0C ptr unkC; 10 ptr segmentsBitfields; 14 ptr segmentsBspTree
18,1A,1C,1E s16 numberOfTextures,numberOfSegments,unk1C,numberOfAnimatedTextures
20 s32 minimapSpriteIndex; 24,26 u16 minimapRotation,unk26; 28,2C f32 minimapX/YScale
30,32,34,36 s16 minimapOffsetXAdv1,YAdv1,XAdv2,YAdv2; 38 u32 minimapColor
3C,3E,40,42,44,46 s16 lowerX,upperX,lowerY,upperY,lowerZ,upperZ; 48 s32 modelSize
Segment: 00 ptr vertices; 04 ptr triangles; 08 s32 unk8; 0C ptr batches
10 ptr unk10; 14 ptr collisionFacets; 18 ptr collisionPlanes
1C,1E,20 s16 numberOfVertices,numberOfTriangles,numberOfBatches; 22 u8 pad[6]
28 s16 unk28; 2A,2B s8 unk2A,hasWaves; 2C ptr unk2C; 30,32 s16 unk30,unk32
34 ptr unk34; 38 s16 unk38; 3A u8 pad[2]; 3C s32 unk3C
40 u8 numberofOpaqueBatches; 41 u8 pad[3]
```

`src/tracks.c:2832-2888` fixes offsets relative to the decompressed model base
(including segment vertices/triangles/batches/collisionFacets). TextureInfo is
8 bytes: 00 u32 texture ID, 04..06 u8 width,height,format, 07 s8 surfaceType.
Segment bounds are C bytes (`>6h`); BSP node is 8 (`>hhBBh`). Batch ranges use
the NEXT batch's offsets, including a terminal batch (`src/tracks.c:1943`).

**TriangleBatchInfo: C (12)** = `>BbhhBBI`: 00 u8 textureIndex (FF none),
01 s8 vertOverride, 02 s16 verticesOffset, 04 s16 facesOffset, 06 u8 miscData,
07 u8 texOffset, 08 u32 flags. **Vertex: A (10)** = `>hhhBBBB`: 00/02/04 XYZ,
06..09 RGBA. **Triangle: 10 (16)** = `>BBBBhhhhhh`: 00 flags, 01..03 indices,
04/06 uv0, 08/0A uv1, 0C/0E uv2, ALL six UV components signed s10.5.
Index = batch.verticesOffset + triangle index. Flag 40 draws backfaces.
`include/f3ddkr.h:161-175` confirms custom vertex and 16-byte triangle commands.

**TextureHeader: 20 (32)**:

```text
00,01,02 u8 width,height,format; 03,04 s8 posX,posY; 05 u8 numberOfInstances
06 s16 flags; 08 s16 ciPaletteOffset; 0A s16 numberOfCommands; 0C ptr cmd
10,11 u8 unk10,unk11; 12 u16 numOfTextures; 14 u16 frameAdvanceDelay
16 s16 textureSize; 18..1C u8 unknown[5]; 1D u8 isCompressed; 1E,1F u8 unknown[2]
```

Disk frame count is byte 12 (runtime reads BE u16 >> 8); tool uses two bytes
at 12/13. Format low nibble: 0 RGBA32, 1 RGBA16, 2 I8, 3 I4, 4 IA16,
5 IA8, 6 IA4, 7 CI4, 8 CI8. Flags 40/80 clamp U/V, 400 line swap (the C
header's 04 interlace comment is stale; RenderFlags/extractor agree on 400).
Compressed textures have an outer 20-byte header then the Rare stream, whose
output includes frame headers. CI palettes come from section 14 (32 bytes CI4,
128 bytes CI8 in the loader). Source: `src/textures_sprites.c:455-556`,
`src/textures_sprites.h:42-57`, tool `extractTypes/extractTexture.cpp:15-76`.

**Rare gzip:** NO 1172 magic in these DKR streams. Bytes 0..3 are the
uncompressed u32 length in LITTLE-ENDIAN, byte 4 is 09 (compression level),
raw DEFLATE begins at +5; compressed entries may have 16-byte trailing padding.
Sources: `src/gzip.c:36-65`, `libs/gzip/DKRCompression.cpp:15-34`. Read-only
ROM checks: model 0 header `3a13020009` inflates to 135994 bytes; object map 0
`a010000009` inflates to 4256 bytes; both match declared sizes exactly.

Additional roadmap correction: object common entry is 8 bytes, ID = byte0 |
((byte1 & 80) << 1), size = byte1 & 7F, then BE s16 XYZ. IDs pass through
`ASSET_LEVEL_OBJECT_TRANSLATION_TABLE` (section 35) to object headers, then
behaviorId; the original contiguous-bitfield description was incorrect.
Sources: `include/level_object_entries.h:13`, `src/objects.c:1943`.


## Phase 2 refinements (2026-10-19)

- Rev 1 object-map table slots 81 and 99 are empty (duplicate offsets).
  `src/objects.c:992` guards `assetSize != 0` before decompression.
- Four language strings are English, German, French, Japanese (`include/enums.h:67`,
  `src/game.c:650`). DKRJP uses two-byte glyph indexes (`text/dkrText.cpp`);
  names are embedded in each extracted header's `name` JSON object.
- Generated manifests are under `assets/.vanilla/us.v80`; `assets.meta.json`
  points to section manifests, whose `files/order` defines indexes and
  `files/sections/<build-id>/filename` defines paths.
- **Phase 5 follow-up:** the common-entry struct comment/extractor say length
  mask 0x7F, but runtime object-map iteration at `src/objects.c:1003-1005` uses
  0x3F. Preserve bit 6 and reconcile against actual entries before implementing
  object parsing; the earlier 0x7F note above describes the tool, not runtime.

## Phase 3 refinements (2026-10-19)

- All 55 model headers have modelSize equal to the inflated length. Offsets are
  relative to the decompressed file base; use the fields, not inferred array order.
- A segment has numberOfBatches + 1 batch records. Only the terminal record's
  vertex/face offsets are valid; its other metadata can contain unrelated bytes.
  Real batches partition vertices and triangles monotonically from zero to the
  declared counts. Every triangle index is local to its batch's vertex upload.
- BSP contains numberOfSegments - 1 internal nodes. Children -1 denote leaves;
  node segmentIndex splits segment ranges, not a directly drawn leaf.
  Source: tracks.c:1986-2035. All 55 models pass offset/graph validation.
- The display path skips batch flag RENDER_HIDDEN=0x100 (tracks.c:1914). Triangle
  flag BACKFACE_DRAW=0x40 disables culling for that triangle. Collision normals
  use the original vertex ordering (tracks.c:3111-3113); preserve OBJ winding.
- The loader changes vertices with R=G=1 into RGB 128/128/128, alpha=stored B
  (tracks.c:2895-2918). Raw RGBA is retained, and display/export RGB follows
  this fixup. Phase 3 renders solid colors; alpha/materials remain Phase 4.
- Known model counts: Central Area/model 0 = 41 segments, 4427 vertices, 3425
  triangles; Ancient Lake/model 5 = 24 segments, 1671 vertices, 1156 triangles.
  Total across all 55 = 125245 vertices, 90617 triangles.

## Phase 4 texture refinements (2026-10-19)

- `TextureHeader` remains 0x20: byte 0x12 is disk frame count, 0x14 BE u16
  frame advance, 0x16 BE s16 frame stride, 0x1D compression. Retain raw headers.
  Compressed outer headers precede a Rare stream containing full frame records.
  All 1416 Rev 1 3D entries decode to 1713 frames / 1961824 texels.
- Entry format counts: RGBA16 1136, RGBA32 237, IA8 37, I4 3, I8 2, IA4 1.
  No IA16/CI textures occur in this ROM. Palette section 14 is empty at
  0x38D810; CI4/CI8 tests supply synthetic BE RGBA16 palettes. Generic CI8
  decoding supports 256 supplied colors; the game's loader reads only 64.
- `imageHelper.cpp:191-224` swaps adjacent 4-byte blocks on odd rows, with
  8-byte blocks for RGBA32; partial groups remain untouched. Flag 0x400 marks
  pre-swapped data. `material_init` at textures_sprites.c:1505 uses special
  load macros for these pixels, not a CPU row swap. Viewer undoes it once.
- Width/height not powers of two also force clamp, in addition to 0x40/0x80
  (`material_init`:1477-1503). No mirrored wrap mode is set here.
- `extractTexture.cpp:31-42` deinterlaces then optionally flips PNG vertically;
  `flipped-image` records this. Viewer canonical rows stay top-to-bottom N64
  order. GL uploads unchanged rows, uses signed UV/(32*[width,height]); OBJ
  uses (U, 1-V) with the same top-to-bottom PNG. No clamping of UV values.
  Per-corner coordinates prevent seams at shared vertices.
- texOffset is not a UV offset. `tracks.c:1953` shifts it left 14;
  `material_set`:704-705 selects frame >>16 if in range. Thus a static batch
  selects byte texOffset//4 when < 4*frameCount, else frame 0. Every frame is
  parsed; runtime animation/pulsing/scrolling/wave generation is not simulated.
- RGBA16 uses BE5551; RGBA32 is RGBA bytes. IA16 is I8+A8, IA8 I4+A4,
  IA4 I3+A1; 4-bit pixels use high nibble first. I4/I8 export opaque alpha as
  local n64graphics does. IA4 scales 3-bit intensity over the full 0..255
  range; local n64graphics uses an approximation (*36, max252).
- The renderer skips hidden batches, draws opaque/cutout surfaces first,
  then sorts translucent batches far-to-near with depth writes disabled.
  Flags/format modes select blending; RENDER_VTX_ALPHA is 1<<27, enabled by
  the (1,1,B) loader encoding, RENDER_DECAL=0x800, WATER=0x2000.
  Source: textures_sprites.h:42-73, material_init:1507-1565, tracks.c:1903-1979.
  This is a static track preview, not the full N64 combiner/fog/wave pipeline.
- Material export includes all segments/hidden batches, per-corner vt and
  one-based v/vt references, materials per texture ID/stored frame, map_Kd
  PNGs and map_d alpha-channel references where alpha exists. PNG folders
  include a content digest. Safe ASCII MTL basenames avoid spaces in mtllib.
  Staged writes publish OBJ last and restore prior MTL on failure.
- Actual GPU probes verified raw UV orientation, repeat sampler, alpha0
  holes, alpha 20/255 discarded versus 30/255 retained, and alpha128 blending.
  GPU sweep covered all 65 catalog levels / all 55 models / 569 texture IDs.

## Phase 5 object and route verification (2026-10-19)

- Object table section33 at 0x6CBC40..0x6CC110 maps 304 ASSET_OBJECTS
  section34 entries at 0x6CC110..0x6D79D0. Section35 translation is
  0x6D79D0..0x6D7DD0: exactly 512 BE signed halfwords; 512 means unmapped.
  Object IDs use 9 bits and are not header or behavior IDs.
- ObjectHeader fixed struct is 0x78 bytes, with trailing arrays in its asset.
  Scale is BE f32 at0x0C, signed behavior ID at0x54, ASCII name[16] at0x60.
  Preserve the complete header asset; do not dereference runtime pointers.
  Source: include/structs.h:798-852, objects.c:894-912 and1943-1951.
- Inflated object maps start with a 16-byte header: BE u32 ENTRY PAYLOAD size
  at0 and 12 reserved bytes. The extractor's fileSize comment is misleading:
  both extractObjectMap.cpp:90 and runtime objects.c:999-1005 add the header.
  The payload ends exactly at 16+size, followed by 0,2,4 or6 zero alignment
  bytes in Rev 1. Preserve those bytes and the reserved header fields.
- Common entry 8 bytes: >BBhhh. ID = byte0 | ((byte1 & 0x80)<<1); runtime
  size = byte1 & 0x3F. Bit6 is preserved separately. None of 9426 entries
  sets it, so the tool's 0x7F mask yields identical lengths for this ROM.
  All 128 behavior-to-struct mappings from default-object-entries-order and
  include/level_object_entries.h match every entry's exact byte size.
- There are 136 nonempty map slots, with vacant slots81/99. Entry length
  distribution: 8:860, 10:418, 12:2198, 14:38, 16:285, 18:68, 20:164,
  22:65, 26:46, 28:1265, 30:2, 50:4017. All bytes reconstruct exactly from
  header + raw entries + alignment. Known maps:0=209,5=98,73=86 entries.
  Ancient Lake uses maps73 and5 =184 objects. Both map IDs are loaded once
  when they coincide; negative map IDs mean absent maps.
- Checkpoint struct 28 bytes: scale8, index9, angleYA, s8 lateral lanes B..E,
  s8 vertical lanes F..12, s8 lane behavior selectors13..16, alt17, unk18/19,
  s8 vehicleType1A, unk1B. vehicleType chooses a checkpoint SET, not a vehicle
  identity. game.c:492-497 maps vehicle through LevelHeader s8[3] at0x4F.
  Central Area maps (0,1,2). The four AI lanes use racer->unk1CA, independently
  of vehicle choice (racer.c:9060-9064).
- Checkpoints sort by index within their set; alternates replace the matching
  main checkpoint index (objects.c:5557-5642). Main loops close back to first.
  Viewer displays the alternate replacement loop and directional arrowheads.
  No duplicate checkpoint IDs arise when combining the two maps of any level.
- U8_ANGLE_TO_U16 is x<<10 (src/object_functions.h:12), so yaw is byte/64
  turns. Checkpoint scale is max(byte,5)/64 in obj_init_checkpoint, then *2
  in checkpoint_update_all. Lane point offsets are therefore scale/32 times
  (cos(yaw)*lateral, vertical, -sin(yaw)*lateral). Catmull-Rom coefficients
  match objects.c:9642; the viewer samples 12 subdivisions per connection.
- AiNode struct16 bytes: unk8, nodeID9, adjacent[4]A..D, s8 elevationE,padF.
  NODE_NONE=255; runtime accepts nodes/targets with bit7 clear. Adjacency
  creates a directed graph, not a sequential spline loop. Unlinked nodes are
  retained as markers. Source: objects.c:7328-7400, object_functions.c:4183.
- Object scene categories derive from verified behavior IDs. Gizmos are batched
  line spheres/boxes and yaw arrows, drawn as overlays through the mesh.
  Picking unprojects Qt logical pixels into a normalized ray, intersects visible
  marker spheres and chooses the nearest hit. Category/search filters constrain
  both rendered markers and picking. The selected marker has a larger amber
  outline. A tree-row double-click fits a local camera box around its position.
- Extracted source support follows generate_section_json_file's single-file
  filename case and files/order case. ObjectHeader JSON resolves behavior/name;
  translation JSON has a nullable table array. Map JSON objects points to a
  glTF objects root; child translation + extras retain decoded struct fields.
  Angle/Scale/Time hints are reversed for inspection. Original alias ID, byte
  offsets, bit6 and raw bytes cannot be recovered from glTF; these are explicitly
  marked unavailable, with the first matching translation ID used canonically.
- Headless gate: 390 passed. All 138 maps / 9426 entries validated. GPU sweep:
  all 65 catalog levels, 9341 loaded object instances, largest301 (Windmill
  Plains), all-lane/marker/selection paths, no GL errors. Final Ancient Lake
  smoke passed actual double-click focus, ray picking, filters and synchronization
  on RTX4060 at63.4FPS / GL3.3Core / 4xMSAA. FPS is measured in a normal Qt
  event loop; QTest polling alone under-reports the refresh rate.

## Sprite scenery extension (2026-10-19)

- `include/structs.h:156` SpriteAsset has a serialized fixed part of12 bytes:
  BE s16 baseTextureId at0, s16 numberOfFrames at2, signed anchor X/Y at4/6,
  unused s32 at8, then u8 frameTexOffsets at12. The C declaration includes a
  one-byte array placeholder and alignment; do not use its padded sizeof as
  the serialized offset. `tools/.../fileTypes/sprite.hpp` explicitly defines
  the12-byte SpriteHeader. Read numberOfFrames+1 offsets. They start at0 and
  are nondecreasing; equal offsets mean a blank frame. Frame f references
  baseTextureId+[offset[f],offset[f+1]) in TEXTURES_2D. The193 definitions
  contain600 frames and reference729 unique 2D textures.
- TextureHeader posX/posY at3/4 are signed bytes. For each tile, let
  x=posX-anchorX and y=anchorY-posY. sprite_init_frame at1306 creates corners
  (x,y-1), (x+width-1,y-1), (x+width-1,y-height), (x,y-height).
  UVs are leftU=1/32 pixel, rightU=width-1 pixels, topV=0,
  bottomV=height-1 pixels, divided by texture dimensions for GL. Preserve the
  N64 row orientation and signed offsets; tiles already encode their layout.
  Beachtree sprite107 has3 tiles, anchor(82,122), local bounds(-34,-6)..(33,116).
- tex_load_sprite at950-1047 loads all consecutive 2D tile IDs. One2D texture
  (ID1) has a final frameSize2768 but only2760 decoded bytes including its
  header/pixels. frameSize is the stride to a following frame, so require that
  stride to fit only when another frame exists; final alignment padding may
  be absent. Every one of916 2D textures decodes under that rule.
- ObjectHeader modelType signed byte0x53=1 is SPRITE_BILLBOARD. Its modelIds
  pointer at0x10 is an asset-relative BE u32 array; signed count is0x55,
  distinct from behaviorId at0x54. Scenery uses entry.modelIndex with fallback0;
  weapon balloons use balloonType in BOOST/MISSILE/TRAP/SHIELD/MAGNET order.
  object_functions.c:113 and492 scale scenery/torch by header.scale times
  max(radius,10)/64. Weapon/golden balloons use max(entry.scale,10)/64;
  bananas, coins and buoys retain header scale. Keep the2D cache distinct
  from3D texture IDs. Extracted ObjectHeader models and Sprite start-texture
  references resolve through their own section files/order.
- camera.c:1057 render_sprite_billboard and hasm/math_util.c:472 mtxf_billboard
  use the camera-facing plane, including pitch. The GL shader uses view right/up
  vectors, instance position and scale. Cutouts write depth before translucent
  track surfaces; partially transparent sprite pieces blend back to front.
  Blended track batches and sprite pieces are sorted within their layers;
  intersecting translucent effects are not a full N64 rendering simulation.
- Physical direct-map sprite behaviors covered: scenery2, weapon balloon17,
  torch/mist28, banana32, buoy36, fly coin76, golden balloon77, silver coin88
  and gold coin110. Camera/sound/path helpers can also have sprite models but
  are invisible in the game and remain editor gizmos. Runtime animation
  spawners, object3D models and vehicle-part sprites are outside this milestone.
  Rendering uses frame0, independently of gizmo visibility/category filters.
- Verified:409 headless tests; all65 levels/2202 sprite instances render with
  no GL errors. Ancient Lake has67 instances/140 tile quads including22 scenery
  objects. Real RTX4060 smoke passes existing controls and sprite toggling at
  63.0FPS, GL3.3Core,4xMSAA. GPU probes verify stable artwork under yaw/pitch,
  foreground depth occlusion and transparent holes revealing the background.

## Phase 7: Object edits, projects and ROM export (2026-10-19)

- Every entry's common XYZ is BE s16 at offsets2/4/6; object ID/size prefix
  bytes0/1 is preserved. Editing operates on copies of the original raw entry,
  keyed by map ID and entry index. Typed properties use the verified struct
  schema; advanced raw edits cover every byte at8..entrySize-1, including
  padding/unknown fields. There is no guessed interpretation or normalization
  of unknown bits. Multi-byte values reparse in BE order. Entry length, object
  IDs, map reserved bytes, original entry order and alignment remain unchanged.
- A feasibility sweep packed197797 scalar parameter values across9426 entries
  without changing any bytes.120 maps contain objects,16 are header-only,2 are
  vacant. Coordinate edits/recompression/reparse passed in all120 populated
  maps. Changing scenery radius updates the sprite scale; moving a checkpoint
  updates the computed route. History stores map snapshots; undo/redo and
  reverting one object retain all unrelated bytes. No Qt/GL imports in editing.py.
- `.dkrproj` JSON format `dkr-object-project`, version1: original ROM SHA-1/path,
  selected level, and changed entries identified by map/index/object ID/base
  entry SHA-1. Each stores only changed byte offsets/values, not full assets.
  Duplicate entries/offsets, altered identity/size prefix, invalid ranges,
  incorrect base hashes and unsupported versions are rejected before applying
  a project. Reopening uses the original verified ROM plus the saved overlay;
  the stock ROM loader continues to reject modified-ROM hashes.
- Export recompresses only changed maps using LE u32 decoded length +09 +raw
  DEFLATE, padded to16 bytes (DKRCompression.cpp). All unchanged compressed
  entries and the object-map section tail are copied verbatim. Section20's
  subtable offsets are rebuilt, retaining its FFFFFFFF terminator/padding;
  section21 holds the repacked maps. All50 master starts/terminal end are
  updated relative to LUT_END. The other48 asset sections retain exact bytes.
  Source: buildObjectMap.cpp:142-208 and asset_loading.c:58-81.
- One-unit movement of map95's first entry grows its compressed slot by16
  bytes. Export relocates following sections by16 rather than overwriting them.
  The original12MiB ROM has FF padding after logical asset end0xB8CFD0;
  growth must fit existing padding. The exported file stays0xC00000 bytes and
  BE z64. No-edit export is byte-identical to the normalized original ROM.
- N64 checksums implement tools/n64crc.c:92-163: CIC identified from bootcode
  CRC32 over40..1000; Rev1 is6103 (boot CRC0B050EE0), seedA3886759. The
  checksum window is1000..101000 and CRC1/2 are written at10/14. The master
  LUT lies inside that window, while object-map data lies outside, so moving
  assets can change checksums even though executable code remains untouched.
  Independent C# uint arithmetic cross-checks against the local C algorithm
  pass: stock E402430D/D2FCFC9D, grown-map export E4023EED/52B5CFF1.
- Saves stage a temporary file beside the destination and replace atomically.
  Original-ROM path, insufficient capacity and failed replacements preserve
  prior files. Project saves mark the overlay clean; ROM export is separate.
  Active property editors commit before saving/history/source changes. Save,
  Discard and Cancel preserve the expected project state, including reopening
  the same project just saved. Level switches retain edits and global history;
  live refresh preserves selection/filter/camera and rebuilds affected previews.
- Gate:445 headless tests, including36 edit/project/export tests; all65 levels
  and2202 sprite instances render through the edit-session path with no GL
  errors. Actual Qt delegate/XYZ/nudge/bit edits, invalid values, active-cell
  saves, cross-level undo/redo, project reload and ROM export pass at63.8FPS
  on RTX4060, GL3.3Core/4xMSAA. Unknown gameplay effects and emulator boot/play
  are not verified; exported ROMs are ready for user testing in-game.

## Phase 8: Mouse object translation (2026-10-19)

- No binary format changes. Mouse movement patches only BE s16 XYZ at entry
  offsets2/4/6. The headless edit session snapshots the current map at press,
  previews without adding history, and commits one undo record on release.
  Cancel restores that snapshot and preserves prior undo/redo and dirty state;
  a no-op click preserves redo. Concurrent writes/serialization are rejected
  during a preview; the GUI resolves the gesture before save/history actions.
- Logical Qt pixels drive projection and hit testing, independent of display
  scaling. Float64 inverse projection avoids far-plane precision jitter at
  large N64 coordinates. Handles are approximately90 logical pixels long;
  an axis drag intersects a camera-facing plane containing that world axis.
  Center/artwork dragging uses the camera view plane. Degenerate end-on axes
  cannot start a drag. Initial ray anchors prevent a jump on press; positions
  round to integers and clamp to signed16. Ctrl snaps deltas to the inspector
  Step relative to the original position. Movement does not conform to terrain.
- Sprite picking intersects the current billboard plane and each tile's real
  anchored bounds. UVs match SpriteMesh, including leftU=1/32 pixel; bilinear
  alpha sampling uses the shader's0.1 cutoff, so transparent holes do not select
  the artwork. Actual sprites remain selectable with object markers hidden.
- Live previews preserve the camera, inspector tree expansion and selected
  object. Position-only changes reuse sprite textures/programs/VAOs and marker
  meshes, updating vertex buffers and affected checkpoint/AI route points.
  Property/frame/scale/visibility changes use the full rebuild path. The GPU
  resource reuse is checked in the native smoke test, including checkpoint moves.
- Gate:455 headless tests and native Qt mouse tests pass: all three axes,
  view-plane/artwork drags, snapping, no-op/cancel/focus/disable, single undo/redo,
  level switching and saves during a drag. Project/ROM export retains the moved
  coordinates and other entry bytes. RTX4060 GL3.3Core/4xMSAA smoke63.2FPS;
  timed continuous drags measured53–64FPS after incremental preview updates.
  All65 levels (9341 level-object references,2202 sprite instances) pass live
  preview/cancel with handles visible, original entries restored and no GL errors.

### Camera speed follow-up: v1.3.1

- Object focus previously called Camera.fit_bounds, which overwrote movement
  speed with0.8 times the small fitted radius. Deselection did not restore it.
  Framing now changes only the view/clipping configuration. The viewport sets
  normal speed from the whole model's radius on model load, using the existing
  max(radius*0.8,1) rule. Reset, segment fitting and object focus do not set speed.
- The separate Camera controls toolbar has a1–400% slider;100% retains normal
  scene movement and Shift retains its additional4× boost. The percentage is
  retained across level changes for the current session. This is a viewer
  preference, independent of object movement Step, project overlays and ROM data.
- Verified:456 pytest tests, including fixed speed/displacement across small and
  large fits. Native mouse/keyboard slider input and timed WASD movement verify
  unchanged travel before/after selection, focus and deselection, and twice the
  distance at200%. Fit/isolation/level-change checks and the full editing/mouse/
  export smoke pass, GL3.3Core/4xMSAA on RTX4060 at63.2FPS; empty startup62.6FPS.

## Weapon balloon byte0x08 investigation (2026-10-19)

- User experiment: map73/entry76, WeaponBalloon, changing unk8 from0 to1 did
  not visibly change collection in-game. This12-byte entry is declared in
  include/level_object_entries.h:193: common8 bytes, u8 unk8 at8, balloonType
  at9, scale atA, padB atB. Keep the raw byte editable and named unk8; its
  original design purpose has not been established.
- src/object_functions.c:4647-4698 initializes weapon balloons. The only direct
  reference to this entry's unk8 is the sanity check at4671: values>=6 are
  replaced with0 in the in-memory entry; values0..5 remain. It is not copied
  into the runtime balloon state. The decomp itself comments that it may be unused.
- The same initializer sets modelIndex and properties.weaponBalloon.balloonID
  from byte9 balloonType; scale is header.scale*max(byteA,10)/64. Balloon-color
  cheats override balloonType, and Disable Weapons frees the object. The loop
  at4705-4813 handles collection, item upgrade/quantity, effects and respawn
  without reading the spawn entry's unk8. Upgrades depend on the racer's prior
  held type/quantity, challenge rules and Maximum Power Up cheat. Generic spawn
  code at objects.c:1927 reads common ID/size/XYZ, then dispatches this initializer;
  the cross-reference scan found no additional weaponBalloon entry consumer.
- Read-only scan of all138 original Rev1 map slots found500 weapon balloons:
  492 store0 and8 store4 at byte8. Original map73/entry76 is at(-1685,109,-9850),
  raw1c 0c f9 6b 00 6d d9 86 00 01 42 00. Nonzero stock values alone do not
  establish functionality. Conclusion: apparently unused/sanitized field in
  this revision; changing0 to1 is expected to have no gameplay effect.
- Runtime confirmation method: break on initializer0x8003E00C from
  ver/symbols/symbol_addrs.us.v80.txt:614, identify the selected spawn entry,
  then watch reads/writes of its RAM byte+8 through spawn/collection/respawn.
  The pickup loop symbol is0x8003E180. Expected relevant accesses are the
  initialization check and conditional reset, with no pickup use. Start before
  loading the level and distinguish bulk copying from semantic field reads.
  Compare0/1/5/6;6 should be reset to0. A changed byte9 balloonType provides a
  known working export/control experiment with color cheats disabled. This
  debugger trace has not been run; findings above are source and ROM inspection.

## Checkpoint field investigation (2026-10-19)

The complete byte-by-byte mapping, behavior codes, HUD enum, stock distributions
and controlled test procedure are in [CHECKPOINT_FIELDS.md](CHECKPOINT_FIELDS.md).
Source trace confirms lateral lanes atB..E, vertical atF..12, per-lane behavior
selectors at13..16 (equality-tested codes, not bit flags), HUD course cue at19,
and apparently unused18/1B. All1256 stock checkpoints have18=-1 and1B=0.
The screenshot's map5/entry48 is index0/set0, with scale95 and lateral values
[-53,-15,28,64]. An independent in-memory edit of unkB from-53 to-43 moves
only AI lane0's control point +29.6875 in X; other lanes and bytes are unchanged,
and undo restores the original entry. No application or ROM files were changed,
and no new gameplay/debugger run is claimed.

The v1.3.2 inspector now uses friendly checkpoint labels with original source
names in hover help. UI metadata is confined to object_inspector.py; no core
schema, project or ROM format changed. Lane behavior/HUD cue/alternate cells
offer editable numeric choices, retaining arbitrary unlisted values.18/1B remain
apparently unused and code3 unidentified.456 headless tests and native Qt checks
pass labels/help, real popup selection, signed/raw input, invalid range rejection,
undo/redo, saving an active choice and exact project/ROM byte round trips.
Full GL/editor/mouse smoke passes on RTX4060, GL3.3Core/4xMSAA at62.5FPS.
