# Stock track reconstruction

The stock compiler reconstructs existing USA Rev1 track data without functional changes.
It shares format validation with the custom-track importer. Stock collision
relationships, segment bounds, BSP and visibility remain exact; this operation
does not generate new topology, collision adjacency or visibility.

## Use the editor

1. Open the original ROM/project and select a level.
2. Open **Geometry → Verify stock rebuild…**.
3. Choose **Verify selected stock track** or **Verify all stock tracks**. Checks
   run on a worker thread; **Stop** and closing the dialog cancel after the
   current model. The report shows identity, record coverage, runtime memory,
   compression and the combined ROM layout.
4. Use **Copy report** to retain the findings. Verification writes no ROM.
5. If you want to test the result in-game, choose **Export stock rebuild ROM…**
   and select a new filename. A successful run enables this explicit export.

This is an **original-ROM stock export**. Existing geometry/object/artwork edits
stay in your current project and are not included. Normal **Save As Edited ROM**
still exports project edits. Continue editing against the original ROM/project;
the editor's verified-base check does not accept exported ROMs as a new base.
Existing projects keep their current v6/v7/v8 formats and writer permissions.

For gameplay review, use a fresh load of the exported ROM and compare normal
racing, collision, appearance and segment transitions against stock. A rebuilt
track should behave exactly as before. The user performs this test; the agent
does not generate review ROMs or run emulator playtests automatically.

## What is rebuilt

`src/core/track_rebuild.py` decodes explicit typed records and packs them into a
new zero-initialized output buffer. A separate set of opaque spans fills the
complement. Every byte must have one owner; overlaps, missing bytes, malformed
references and changed stock payload hashes are rejected.

| Record | Size | Source-backed handling |
|---|---:|---|
| LevelModel | 0x4C | All fields re-encoded; minimap float members retain their exact IEEE u32 bit patterns. |
| LevelModelSegment | 0x44 | Seven initial words, counts, padding, visibility offset, wave/runtime members and opaque batch count retained. Includes the pointer at0x34. |
| TextureInfo | 8 | Original texture references and legacy dimensions/format/surface retained. |
| Vertex | 10 | Signed16 XYZ and original RGBA bytes retained, including the R=G=1 loader encoding. |
| Triangle | 16 | Flags, batch-local u8 indices and all six signed16 UVs re-encoded. |
| TriangleBatchInfo | 12 | Batches plus terminal record; original offsets, flags and terminal garbage preserved. |
| CollisionFacetPlanes | 8 | Four u16 values; base/neighbor relationships remain original. |
| Segment box | 12 | Six signed16 bounds retained. |
| BSP node | 8 | Child indexes, axis, segment split and signed split position retained; leaf coverage checked. |
| Visibility row | ceil(segments/8) | Located through each segment's signed offset at0x28, with low-bit-first target selection; unused high bits retained. |

Unsupported spans and uninterpreted struct members remain exact. Re-encoding
their storage does not establish their meaning. The model's layout and counts
remain stock. This goes beyond the local decomp tool's raw-copy builder, but is
not a completed custom-track compiler.

## Runtime and export checks

The source-model loader checks derive inclusive eight-by-eight XZ masks,
float32 base and edge-bisector collision planes, reciprocal facet fixups with
bit15 inversion, water batch indexes and the first-vertex water-height selection.
They compare results before and after reconstruction. Render-hidden geometry
still participates in collision; TRI_FLAG_80 and No collision follow their
separate source rules. Degenerate normals retain signed zero bits when the
source skips division. Both normal and cutscene base-plane-only paths are checked.

The aligned allocations must fit the fixed0x82A00 (535,040-byte) track heap.
Recompressed LE-u32-size/09/raw-DEFLATE entries pass the existing source-model
in-place inflater check with the track loader's staging position. These checks
model the local C/assembly sources; they do not execute the game.

Only selected stock model entries are recompressed. The existing asset-table,
ROM budget, checksum, source-overwrite and atomic-write protections are reused.
Unselected compressed entries, other asset sections and table/section tails
remain exact. Failed checks leave the project and destination untouched.

All55 stock models reconstruct identically. Ancient Lake re-encodes49,330 of
49,644 bytes, retaining314 opaque bytes. Its normal track allocation is95,680
bytes; cutscene allocation is70,736 bytes. Recompression changes its stored span
from24,912 to24,688 bytes. Recompressing all55 saves5,808 bytes of ROM storage,
leaving476,896 bytes of padding; this does not add game RAM.

Authoritative local references: `include/structs.h:601–763`,
`src/tracks.c:203–212,1681,1885–1980,2031–2045,2395–2408,2832–3222`,
`src/hasm/collision.c:347–358`, and
`tools/dkr_assets_tool_src/{builder/buildTypes/buildLevelModel.cpp,extract/extractTypes/extractLevelModel.cpp}`.

Verification:1,025 full tests passed in158.85s, including78 stock reconstruction
checks. Native RTX4060 GL3.3 selected/all55 runs, cancellation/close, copy/cancelled
export, viewport responsiveness and preservation of dirty geometry/history pass.
Screenshots were reviewed. No agent-generated review ROM or emulator test was
performed. User gameplay review, 2026-10-20: the exported stock rebuild worked
in Central Area and three early tracks with no reported issues. The representative
23A gameplay gate is complete;23B remains pending explicit user authorization.
