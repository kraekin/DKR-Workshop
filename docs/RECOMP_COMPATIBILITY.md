# DKR-R compatibility investigation

Research date: 2026-10-30. User confirmed ThatGuyMcd/DKR-R.
Upstream main inspected at commit d457741b57afff8d2ec96b2307f11c1340a4162f
(reported v1.0.12). This is a source-based feasibility assessment, not a runtime
compatibility claim. No implementation phase, fork, test ROM or emulator run.

## Workshop export behavior

src/core/rom.py requires clean USA Rev1/us.v80, SHA-1
6d96743d46f8c0cd0edb0ec5600b003c89b93755. Its master asset table starts at
0xED0E0, and section data starts at 0xED1B0.
src/core/editing.py::_assemble_rom rebuilds asset sections and master offsets,
retains original ROM length and writes N64 checksums at 0x10..0x17. It preserves
the program preceding the asset table. Local authoritative reference:
research/Diddy-Kong-Racing/src/asset_loading.c; pi_init loads the master table,
and asset loads resolve section starts relative to __ASSETS_LUT_END.

## What upstream already supports

- ROM_SETUP.md: original US v77 and v80 only; legacy patches belong in Mods /
  Hacks, not the game ROM picker.
- rom_revision.cpp::inspect: normalized whole-ROM XXH3 identity selects native
  v77/v80 CPU payloads; an edited ROM is rejected.
- legacy_mod_import.cpp: accepts .xdelta or ZIP containing .xdelta; reconstructs
  target bytes against a user's original ROM with xdelta3.
- legacy_mod_format.cpp::AssetImage: supports both source layouts, reads the
  actual master offsets, and can discover a relocated valid asset directory.
- analyze compares records, including decoded compressed records. Program-byte
  comparison explicitly excludes checksum bytes 0x10..0x17. Unknown patches
  can be structurally detected; this is not a fixed patch-hash whitelist.
- Track roots require race type 0 or bit 0x40 and a changed model, either object
  map, or header. A name/texture/shared-model-only edit does not itself identify
  a track root. Hubs and whole-game Adventure replacement are not implied.
- legacy_mod_dependencies.cpp traverses track geometry, maps, object headers,
  sprites, textures, object models and animation dependencies. Format and size
  checks can refuse content (e.g. combined maps over 512 placements).
- legacy_track_materialize.cpp prepares isolated course banks and reports
  excluded changed records; other stock courses/global state stay original.
- CUSTOM_TRACKS.md: .dkrmap adds courses through data/table hooks. Covers level
  headers, maps, names, models, 3D/2D textures and sprites; uses runtime ID
  fixups, explicit structure/collectables map slots and patchable model prefix.
  It is not a general shared object-header/model/animation overlay format.

## Recommended sequence

1. Small offline compatibility proof using the existing xdelta importer:
   original v80 + Workshop project -> edited bytes -> xdelta patch. Validate
   patch reconstruction and upstream analysis/dependency reports headlessly.
   User performs any in-game verification, following project preferences.
2. If that succeeds, scope a Workshop Export for DKR-R action, initially with
   explicit supported edit categories and excluded-edit reporting. A .dkrmap
   exporter is an alternative for standalone additive courses, requiring ID,
   map-slot, texture, minimap and compression-prefix conversion.
3. For whole edited-ROM/Adventure fidelity, investigate an upstream extension
   or compatibility fork. Validate the original base, compare protected program
   bytes (allow checksum changes), bind the v80 CPU payload explicitly, serve
   the edited asset tables/data consistently, audit native stock assumptions,
   isolate saves and identify content for caches and any later online work.
   Merely removing one ROM hash check does not prove compatibility.

No path is verified to reproduce all Workshop changes yet. Next requires a
separately authorized implementation milestone; research itself is complete.

## Primary sources

- https://github.com/ThatGuyMcd/DKR-R/blob/main/docs/ROM_SETUP.md
- https://github.com/ThatGuyMcd/DKR-R/blob/main/docs/ARCHITECTURE.md
- https://github.com/ThatGuyMcd/DKR-R/blob/main/docs/CUSTOM_TRACKS.md
- https://github.com/ThatGuyMcd/DKR-R/blob/main/runtime-recomp/src/game/rom_revision.cpp
- https://github.com/ThatGuyMcd/DKR-R/blob/main/runtime-recomp/src/game/mods/legacy_mod_import.cpp
- https://github.com/ThatGuyMcd/DKR-R/blob/main/runtime-recomp/src/game/mods/legacy_mod_format.cpp
- https://github.com/ThatGuyMcd/DKR-R/blob/main/runtime-recomp/src/game/mods/legacy_mod_dependencies.cpp
- https://github.com/ThatGuyMcd/DKR-R/blob/main/runtime-recomp/src/game/mods/legacy_track_materialize.cpp

## Selected route and implemented preview

The user selected the whole-ROM fork route and required approval before any
Workshop code change. Workshop code remains unchanged. A separate local fork is
at research/DKR-R-workshop, branch workshop-whole-rom. It now builds a Windows
x64 preview using a reviewed v80 ELF prepared from the authoritative LOCAL
source. All 3,829 functions were generated with existing native hooks.

The fork validates original v80/program provenance, installs the complete edited
cartridge before guest entry, retains IDs and relocated tables, and scopes its
profile to the edited image. It has an offline Windows ROM picker and CLI.

Preview: artifacts/DKR-R-Workshop-preview/DKR-R-Workshop.exe. See the fork's
docs/WORKSHOP_ROM.md and docs/notes/2026-10-30-workshop-rom.md for exact tests,
limitations and the outstanding historical snapshot-pin tooling result.
Native parser/actual PI/in-memory Workshop export checks pass. Gameplay/GPU
acceptance is reserved for the user; no gameplay/test ROM was generated and no
game/emulator was launched. The earlier xdelta recommendation is superseded by
this user-selected implementation route.

## Stock-client direction (user follow-up)

The user reports the preview works with an edited ROM and now prefers official
DKR-R compatibility for sharing hacks. Current upstream ROM setup still requires
clean cartridge identities. Exporter changes alone cannot make a changed whole
ROM match the original whole-ROM hash. Standard .xdelta/.dkrmap imports are the
existing stock-client routes, with the previously documented selective-course
limitations. Full edited-game fidelity should target an upstream whole-asset
mode, using the local fork as working evidence if a contribution is requested.
No upstream contact/submission or Workshop code change is authorized by this
assessment alone; preserve the existing proof and ask before Workshop changes.


## Minimal preview after user gameplay confirmation

At the user's request, removed the optional Windows Workshop picker source,
target and executable. The separate minimal package is
artifacts/DKR-R-Workshop-minimal; its existing DKR-R.exe takes --rom (original
USA 1.1) and --workshop-rom (Workshop export). The prior working preview remains
preserved. Retained only the runtime validation/cartridge handoff and profile/
offline/mod-isolation integration, plus necessary local v80-only build support
and host-only tests. The user has no v77 original; Workshop targets v80 only.

Windows x64 was rebuilt as 1.0.12-workshop-minimal.1. The repeated 62 native ROM
checks, actual librecomp PI DMA/PIO/reload, four real in-memory Workshop exports
and four packaged executable startup refusals pass. No Workshop application
code, generated guest code, dependency pins or user ROM files changed. The
historical frozen-source tooling mismatch remains explicit. See the minimal
package README and fork investigation notes for launch and final host results.
No game was launched; fresh gameplay confirmation belongs to the user.
