# DKR Workshop v0.28.0 — Custom-course finishing

- **Generated minimaps:** generate a top-down track silhouette, select road
  surfaces, filter steep faces, rotate and pad the image, and preview the actual
  N64 result with checkpoint markers for both Adventure modes. Apply artwork
  and marker alignment together as one undo step.
- **Batch image tools:** export selected, filtered or changed images as PNG
  frames or animation sheets. A manifest retains asset IDs, frame indexes and
  orientation. Review the N64 conversion and shared uses before one batch Apply.
- **Unified Course Builder:** checkpoints/branches, AI lanes and start grid now
  share three tabs, one preview, draft history and one Apply. Create paired branches,
  place them on the road or drag their handles, preview entry/rejoin and all
  four AI lanes, generate even lane spacing and optionally fit lane heights to
  nearby road, or adjust individual lane values. Readiness notes highlight pairing,
  lane order and continuity. The separate Route Finishing window is removed.
- **Direct patch export:** export BPS or xdelta patches from the current project
  without first saving an edited ROM or installing a separate patch tool.
  Both formats reconstruct the same validated edited ROM as normal ROM export.
- **Safer scrolling:** scrolling over spinners, dropdowns or sliders now scrolls
  their pane without changing values, including fields that already have focus.
  Use clicks, typing or arrow keys to adjust them; viewport zoom is unchanged.

Existing projects remain compatible. Minimap generation replaces an existing
sprite's first-frame pixels; batch images retain existing dimensions, formats,
tile layouts and frame counts. Shared artwork affects its other users. Route
tools retain the existing checkpoint sets and game data limits; previews do not
simulate racer AI. Gameplay confirmation remains with the creator.

Apply patches to the original **USA Rev 1 / USA 1.1 big-endian `.z64` ROM**.
Opening `.v64`/`.n64` in Workshop normalizes it in memory; exported patches still
expect that canonical `.z64` base. Save `.dkrproj` separately to retain history.

Guide: [Custom-course finishing](CUSTOM_COURSE_FINISHING.md).
