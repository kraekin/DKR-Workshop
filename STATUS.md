# New-object camera placement v0.27.1 — complete (2026-10-30)

Add Objects now defaults to a visible ground hit at the view centre, with a
lower-centre search if needed. Front/Right views query ground at the centre's
viewing depth and check visibility. Selected objects/stale navigation targets
no longer supply default XYZ. Walls/occluded ground/out-of-view or signed16
failures are refused with an aim-at-track message. Integer X/Z resample the
local surface layer, with Y rounded above it; explicit catalog XYZ still wins.
Templates/map choices, one add undo step, camera and cancel state are preserved.

Verification: 1,853 full tests pass in437.59s (zero failures/errors/skips);
28 focused placement/catalog checks pass;132 Python files parse. All55 stock
camera-fit queries checked (49 visible placements, six safe no-ground results).
Native RTX4060 GL3.3 actual catalog Add places RubberTree at(-1540,25,-7607)
above Ancient Lake groundY24; undo/redo/cancel and unchanged camera pass.
JUnit: artifacts/add-ground-final-tests.xml; screenshots: artifacts/add-ground-*.png.

No new binary structs or writer permissions; retain existing signed16 XYZ and
original us.v80 SHA-1 6d96743d46f8c0cd0edb0ec5600b003c89b93755.
Temporary test fixtures removed; no emulator/gameplay or review ROM. Existing
user editors/files remain untouched. Guide: docs/VISUAL_OBJECT_CATALOG.md;
patch note: docs/RELEASE_NOTES_0.27.0.md. Root DKR Workshop.cmd loads new source.

Saved as a local fix checkpoint; nothing pushed/published. Next: user review
of v0.27.1. No additional feature scope is authorized.
