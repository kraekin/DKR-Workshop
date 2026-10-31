# Custom-course finishing v0.28.0 — complete (2026-10-30)

Implemented staged track-to-existing-sprite minimaps with face/slope selection,
quantized preview, both Adventure marker fits and one artwork/alignment Apply;
batch PNG frames/animation sheets with ID/orientation manifest, changed filtering,
conversion/shared-use review and one import undo; visual paired-alternate routes,
road placement/drag draft history, bounded lane generation/road-height fitting
and continuity diagnostics. Direct File-menu BPS and xdelta patch export uses
validated in-memory edited ROM bytes, verifies reconstruction and writes atomically.
Both patch formats require the canonical original USA Rev1 big-endian .z64 base.

Reuses local LevelModel minimap fields0x20..0x3B, TextureHeader0x20, sprite tile
positions and Checkpoint0x1C (level_object_entries.h; game_ui.c:3295/3771;
sprite_init_frame; objects.c:5530..5800). Unknown bytes, aliases, stable identities,
existing image layouts/palettes/frame counts, project versions and stock ROM
identity/length protections remain intact. No native patch tool is bundled.

Verified: full1,888 tests pass in625.89s with zero failures/errors/skips; final43
focused tests pass in29.78s after final refinements.144 Python files parse;
version0.28.0 metadata and diff checks pass. Native RTX4060 GL3.3 actual slots,
menu actions, Apply/Undo/Redo/cancel/camera preservation and both patch formats
pass; no-ROM input/graphics smoke passes61.3FPS/4xMSAA. All55 stock minimap queries:
53 generate, models17/35 safely refuse no suitable faces. Independent xdelta3
reconstructs complete edited ROM in memory; official Floating IPS v198 verifies
synthetic BPS insertion/deletion/relocation. Original ROM SHA-1 unchanged:
6d96743d46f8c0cd0edb0ec5600b003c89b93755. User files/editor sessions preserved.

Guide: docs/CUSTOM_COURSE_FINISHING.md; release notes: docs/RELEASE_NOTES_0.28.0.md.
JUnit/screenshots/interoperability records are under ignored artifacts/.
Owned pytest fixtures cleaned; no gameplay/review ROM or emulator run. Next:
user reviews v0.28.0 using the root DKR Workshop.cmd source launcher and performs
in-game confirmation. Save project separately from patches. Local Git checkpoint
only: no remote push, version tag, release or standalone rebuild was requested.
