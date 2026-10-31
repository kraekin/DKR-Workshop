# Object artwork and animation preview (Rev1 / us.v80)

Local sources: include/structs.h:ObjectModel, tools/dkr_assets_tool_src/fileTypes/
objectModel.hpp, src/object_models.c:model_anim_init/model_init_normals,
src/hasm/obj_animate.s, src/hasm/math_util.c:mtxf_from_transform,
src/objects.c:obj_init_animobject/func_8001F23C and src/object_functions.c.
No assets are embedded; all artwork is read from the selected ROM.

| Section | Absolute ROM start | End | Entries |
|---|---:|---:|---:|
|28 Object model table|0x55B0A0|0x55B6C0|390 + terminal + FFFFFFFF|
|29 Object models|0x55B6C0|0x62B660|390 Rare streams|
|30 Animation ID ranges|0x62B660|0x62B970|391 BE s16 + alignment|
|31 Animation table|0x62B970|0x62C0D0|470 + terminal + FFFFFFFF|
|32 Animation data|0x62C0D0|0x6CBC40|470 Rare streams|

ObjectModel C definition is 0x80; the serialized tool definition is 0x58 and
stock model arrays may start at 0x58. Do not reject them as C-header overlaps.
Offsets: TextureInfo array00, vertices04, triangles08, batches38, animated
mapping4C. Counts: textures22, vertices24, triangles26, batches28, animated
groups4A. fileSize is BE u32 at2C. Vertex10, triangle16, batch12 use the same
layout as track geometry. A final batch sentinel supplies terminal counts.
Array pointers are offsets from the decompressed asset base. Runtime collision,
normals and animation pointers are not consumed as serialized arrays.

The animation mapping is **s16 per mesh vertex**, as assembly `lh`/increment2
shows, despite the C field's s32 pointer. -1 is static. Other values index unique
animated vertex groups. Shared groups have identical original XYZ in all390
stock models. Animation ID ranges use table[model]..table[model+1].

Animation stream after Rare inflation:

1. BE u32 keyframe count L (at least2).
2. 12-byte initial root/head header.
3. n triples of BE s16 offsets, added to the original group vertex XYZ.
4. L-1 blocks:12-byte root/head header, then n triples of signed8 XYZ deltas.
5. 0..15 zero alignment bytes.

Expected size before padding:4 +12 +6*n +(L-1)*(12+3*n). All470 entries match.
Runtime animFrame uses four fractional bits. For integer frame k, accumulate
the preceding k delta blocks. Add `(next_signed_delta * fraction) >> 4`, then
store as signed16; preserve static vertices. Valid displayed integer frames
are0..L-2, using the final keyframe as the interpolation endpoint. The separate
root/head header is not added to ordinary actors' vertex positions. Racer head
transforms and vehicle assemblies are separate rendering behavior.

Animation entry behavior49 is a controller. Only its order0 node creates the
translated `objectIdToSpawn` actor; subsequent nodes are path controls. Ambient
channel20 is always active. The editor also previews one chosen scene channel,
ignores camera targets, and applies the initial XYZ, 256-step yaw/pitch/roll,
target-header scale times max(node scale,1)/64, clip, initial frame and speed.
It does not execute the game's spline/event state machine. It intentionally
shows artwork regardless of save progression and gameplay unlock conditions.

Ordinary models use source-verified initialization rules for variant, yaw and
scale; their clip0 playback is a preview rather than behavior emulation. Lit
batches use the source smoothing-group rule with a neutral preview light;
0xFF batches retain baked vertex colors. Environment mapping/shadows are absent.
Animation vertex buffers and sprite frames reuse GPU resources while playing.
Sprite frame selection uses `((counter &255)*frame_count)>>8` (camera.c), with
source loop speeds for torches/mist, bananas/coins and buoys. Procedural renderers,
particles and dynamic game-spawned assemblies remain outside this milestone.
