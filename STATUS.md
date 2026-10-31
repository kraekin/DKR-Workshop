# Focus-aware wheel editing v0.28.0 — complete (2026-10-31)

Corrected59f582e's overly broad wheel guard per user clarification. Focused
spinners, dropdowns and sliders (including embedded text fields) retain normal
Qt wheel editing. Unfocused controls forward wheel input to their pane without
changing values or taking focus. Keep wheel-only focus disabled and retain click/
tab focus policy. Nested panes, table editors, open dropdowns, scrollbars and
camera zoom continue working. Release notes and regression expectations updated.
No binary/project changes; version remains0.28.0.

Verified32 wheel/unified-builder tests pass in6.46s. Native RTX4060 GL3.3 wheel
checks pass all three Course Builder tabs: focused controls edit, unfocused
controls scroll panes, no focus stolen. Native test coordinates account for
125% display scaling. Camera zoom, session and original ROM remain correct.
146 Python files parse and diff checks pass. Ignored evidence:
artifacts/focused-wheel-tests.xml and artifacts/focused-wheel-native.png.

Previous milestones: adffdde (unified builder),9768968 (finishing/patch export).
Next: user reviews in a freshly launched DKR Workshop. Preserve user files and
existing editor processes. Local changes only; no push, release, standalone
rebuild, emulator or gameplay ROM generated.
