# Track import target audit — 2026-10-23

Confirmed editor bug; production code unchanged during this audit.

Follow-up: fixed in 0.25.7; see [implementation and verification](AUDIT_FIXES_2026_10_23.md).

The supplied edited ROM contains a replacement for Whale Bay (geometry8),
changed maps8/76, three appended textures, and Whale Bay's skybox changed203→211.
Ancient Lake's header5 and geometry5 match stock. Checksums, canonical spatial
layout and the actual compressed stream pass.

## Reproduced sequence

1. Edit Whale Bay's skybox from203 to211. The settings panel queues an update
   with `QTimer.singleShot(0, ...)`.
2. Select Ancient Lake before that callback runs. Tree, selected level, header
   geometry, current model, viewport model and Geometry panel all report5;
   the caption is `Ancient Lake · Geometry 5`.
3. Click the real Geometry **Import OBJ** button. `_show_track_import` first
   calls `_commit_editor`, which processes pending Qt events.
4. The old settings callback runs for8. `_apply_level_setting(8, ...)` calls
   `_refresh_level_settings(8)`, which selects8 if the user has moved elsewhere.
5. `_show_track_import` then reads `current_model.model_id`, capturing8. The real
   dialog builds/applies to8; in-memory ROM output changes geometry8, leaving5 stock.

This uses the same skybox field/value found in the user's ROM. Without the
original unsaved session/event log, it cannot prove their exact historical timing.

## Root cause

- `src/ui/object_inspector.py`, `LevelSettingsPanel._changed`: queues the edit
  with its original level index.
- `src/ui/main_window.py`, `_apply_level_setting` / `_refresh_level_settings`:
  refreshing an older level steals the current selection.
- `src/ui/main_window.py`, `_show_track_import`: captures the import target
  after processing that callback.
- `src/ui/track_import_dialog.py`, `_apply`, and the ROM writer correctly retain
  the captured ID. The redirection happens before the dialog opens.

## Other checks and evidence

Normal imports, rapid switching/filtering, queued geometry edits, and a
programmatic main-level change during compilation retained Ancient Lake's
captured target. Cancelling a preview with an earlier Whale Bay import correctly
left only that earlier edit. These five cases pass; the queued-settings case
reproduces the defect consistently.

Native script: `artifacts/audit_track_import_target.py`; its default runs the
five baseline/stress cases. Invoke with `queued-whale-setting` to reproduce the
defect. Traces: `artifacts/import-target-audit/results.json` and
`queued-setting-repro.json`. Only owned UI windows/in-memory ROM builds were
used. Original/edited ROM hashes and user files/sessions remain unchanged.

## Required correction

An old settings refresh must not change the user's selected course. Capture and
validate the intended import session/level/model before flushing edits, and keep
that target through preview/Apply. Add regressions for queued skybox/other field
changes, switching/history and replaced sessions. A prominent target-course label
would also make the destination easier to review.
