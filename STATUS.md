# Creator workflow — visual catalog verified (2026-10-30)

Visual Add Objects catalog implemented: all 304 types retain their templates,
map/XYZ/structural writer semantics; searchable/category-filtered thumbnail cards,
current-project artwork, selected 3D/sprite/texture previews and safe cancellation.
No favorites/presets/groups. Docs: docs/VISUAL_OBJECT_CATALOG.md.
Local decomp confirms existing 0x78 ObjectHeader, artwork pointer0x10/kind0x53/
signed count0x55; existing 0x58 ObjectModel and 12-byte sprite parsers reused.
No new ROM field, parser layout or project version introduced.

Gate: 1,825 full tests passed in369.39s, final15 catalog/grid/label checks and
six catalog/drag-cancel regressions pass. Isolated native catalog screenshots/
filtering/preview pass on RTX4060 GL3.3. Full native smoke passes at63.0 FPS/
4x MSAA after correcting stale smoke labels/axes/editor lookup, and a preexisting
level-switch ordering bug: cancel drag before committing pending editor cells.
Original ROM/user editors preserved; no emulator/gameplay run. Test exports are
owned temporary fixtures, not user review ROMs.

Next authorized milestone: complete object mesh artwork export (OBJ/MTL/PNG),
preserving existing vertex identities, compact units and batch_N import names.
Finish that milestone with focused/full/native checks before user review.
All commits stay local; no push/publication. Autosave remains deferred.
