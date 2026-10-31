# Creator workflow v0.27.0 — complete (2026-10-30)

Implemented the visual Add Objects catalog and complete object mesh artwork
export. All304 catalog types retain map/XYZ/templates/history semantics, with
ROM/project thumbnails, search/category filters and selected 3D/sprite previews.
Object Models & Animation → Export OBJ + artwork writes current base-mesh drafts,
batch_N MTL and referenced PNG frames with current project pixels, UVs/RGBA,
compact units and original vertex rows. Atomic publication/sidecar protections
reuse the track exporter. No favorites/presets/groups or autosave were added.

Verification: 1,841 full tests pass in432.45s with zero errors/failures/skips;
131 Python files parse; core imports remain Qt/GL-free. All390 stock meshes
export/reimport byte-identically. Native catalog/export and full editor smoke
pass on RTX4060 GL3.3/4x MSAA (62.9 FPS). Background Blender4.4 loads MTL/PNGs
and round-trips static256/260 plus animated240, including a pending model draft.
Regression also fixes preexisting level-switch drag cancellation order; stale
smoke assertions now target current axes/labels/visible editors.

No new binary layouts/writers/project version: retain 0x78 ObjectHeader,
0x58 ObjectModel, 10-byte vertices, 16-byte faces and 12-byte batches/sprites.
Original us.v80 SHA-1 remains6d96743d46f8c0cd0edb0ec5600b003c89b93755.
Temporary test ROM/project fixtures removed. User editors/files are preserved;
no emulator/gameplay run. JUnit: artifacts/creator-workflow-full-tests.xml.
Guides: docs/VISUAL_OBJECT_CATALOG.md, docs/OBJECT_ARTWORK_EXPORT.md;
release notes: docs/RELEASE_NOTES_0.27.0.md. Source launch: root DKR Workshop.cmd.

Local catalog commit0f3fd08; export/version/docs saved as a second local feature
checkpoint. Nothing pushed or published. Next: user review of v0.27.0; no further
feature milestone authorized. Prior DKR-R handoff stays in the feature report.
