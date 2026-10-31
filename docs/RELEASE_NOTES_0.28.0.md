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
- **Safer scrolling:** scrolling over unfocused spinners, dropdowns or sliders
  scrolls their pane without changing values or taking focus. Click or tab into
  a control to adjust it with the wheel. Viewport zoom is unchanged.
- **Validation cleanup:** native smoke checks stay active under Python
  optimization and report explicit failures. Retired the standalone bush research
  experiment. Reviewed hashing uses and marked legacy SHA-1 fingerprints as
  non-security uses while preserving existing project compatibility.
- **Extracted JSON paths:** validate resolved manifest and metadata paths against
  the selected asset root, including linked paths. Explicit ROM/project file
  selection still works across directories.
- **Dependency and animation review:** locked Windows build dependencies and
  concise pinned runtime requirements; About balloons use OS-backed randomness.

Existing projects remain compatible. Minimap generation replaces an existing
sprite's first-frame pixels; batch images retain existing dimensions, formats,
tile layouts and frame counts. Shared artwork affects its other users. Route
tools retain the existing checkpoint sets and game data limits; previews do not
simulate racer AI. Gameplay confirmation remains with the creator.

Apply patches to the original **USA Rev 1 / USA 1.1 big-endian `.z64` ROM**.
Opening `.v64`/`.n64` in Workshop normalizes it in memory; exported patches still
expect that canonical `.z64` base. Save `.dkrproj` separately to retain history.

Guide: [Custom-course finishing](CUSTOM_COURSE_FINISHING.md).
