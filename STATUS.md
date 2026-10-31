# Safe pane scrolling v0.28.0 — complete (2026-10-31)

One QApplication wheel guard protects spinners/text fields, closed dropdowns and
sliders across all windows and dynamically created table editors. Wheel gestures
cannot change values, even in focused controls. Remove wheel-only focus without
changing click/tab behavior; forward complete wheel/touchpad data to enclosing
scroll areas, including nested-pane fallback. Stop forwarding at dialog windows.
Open dropdown lists, scrollbars and viewport zoom remain active. Typing, keys,
arrow buttons and deliberate slider edits still work. Release notes updated.
No binary/project format changes; version remains0.28.0.

Verified48 wheel/unified-builder/audit tests pass in37.87s;62 other editor/input
regressions pass in84.58s; final augmented nested-pane check passes in0.53s.
Native RTX4060 GL3.3 actual wheel events pass all three Course Builder tabs with
focused/unfocused spinners: scrolling, values, focus and draft history correct;
camera zoom works, session and original ROM unchanged.146 Python files parse,
release metadata and diff checks pass. Ignored artifacts: wheel-*-tests.xml,
wheel-ui-regressions.xml and wheel-scrolling-native.png. Owned fixtures cleaned.

Previous local milestones: adffdde (unified Course Builder),9768968 (custom-course
finishing/patch export). Next: user reviews after launching a fresh DKR Workshop
from the root launcher. Existing user files/editor processes preserved. Keep this
v0.28.0 work local: no push, release tag, standalone build, emulator or gameplay
ROM generated for this refinement.
