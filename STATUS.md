# Unified Course Builder v0.28.0 — complete (2026-10-31)

Merged main checkpoints/alternate branches, generated+individual AI lanes and
start grid into one three-tab Course Builder. Shared preview, draft Undo/Redo,
readiness/budget review and one composed Apply/project undo. The global set
selector makes scope explicit; copy-to-vehicle-sets includes branches and requested
lane edits. Main/alternate pairing survives reorder/CP0 changes and newly drawn
unsaved points; deleting a main removes its paired draft data, with Undo restore.

Removed the separate Route Finishing window, menu action and inspector button.
Existing inspector quick checkpoint/lane/AI-link edits remain. Cleanup is under
advanced controls. Preview switches centreline/individual/all lanes; manual lane
values override generation and share draft history. Candidate map views compose
all changes without intermediate session edits. Draft point IDs are editor-only;
no ROM structs, project schema or binary writer permissions changed. Minimap,
batch-image and BPS/xdelta features remain intact. No remote publishing requested.

Verified:1,904 full-suite tests pass in586.47s (zero failures/errors/skips), plus
final9 unified/selection checks in8.26s. Native RTX4060 GL3.3 actual-menu checks
pass for all tabs, branch road placement, generated/manual lane values, grid and
one project Apply/Undo/Redo; original parent camera and ROM unchanged.144 Python
files parse, metadata0.28.0 and diff checks pass. Screenshots/JUnit: ignored
artifacts/unified-course-*. Existing user files/editor processes preserved.

Guides: docs/COURSE_BUILDING.md, docs/CUSTOM_COURSE_FINISHING.md. Release notes:
docs/RELEASE_NOTES_0.28.0.md. Owned test fixtures cleaned after verification;
no gameplay/review ROM or emulator run. Next: user reviews using root DKR
Workshop.cmd. Keep this unreleased v0.28.0 work local; no GitHub push, release tag
or standalone rebuild was performed. Previous feature checkpoint9768968 retained.
