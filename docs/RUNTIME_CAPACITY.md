# Phase 20 follow-up — measured resource research

Current editor: the user-confirmed one-bush experiment and explicit request for
all types led to Phase21 experimental tools; see [OBJECT_EDITING.md](OBJECT_EDITING.md).
Snapshot observations still do not establish a universal runtime reserve.
The disabled-editor/type-gate wording below describes the Phase20 research stage.

v1.13.1 keeps production structural editing disabled. It closes the per-stream
map-inflate check and provides a way to collect runtime evidence before any
Phase21 operation is enabled. No safe positive extra-object allowance is claimed.

## Narrow scenery candidate

All206 previously identified simple scenery placements have calculable object
blocks, but some load shadow textures or react to collisions. A narrower subset
contains58 stock placements:32 `PalmTreeTopChea` (header52, sprite116) and26
`PalmTreeTop` (header50, sprite114). Their existing12-byte entries have four
parameters: modelIndex, radius, angleY and solid. The selected entries have
solid=0, one billboard sprite, zero attachments/emitters/lights and shadowGroup=0.

`object_functions.c:113–183` initializes scale/rotation and optional solidity;
there is no per-placement node/index registration. The only scenery-specific
dispatches in `src/` are the init/loop switches in objects.c. Non-solid entries
cannot enter the loop's collision sound/emission branch. This is bounded source
evidence for ordinary decoration, not a blanket claim about every object that
shares the Scenery schema. Other entry types/references stay protected.

For another instance of a header already present and successfully loaded in
the same map, the verified cost is:

| Resource | Additional demand |
|---|---|
|Object pool block|208 bytes:128 Object +4 sprite pointer +4 default property reservation +12 billboard shading +16 ShadowData +40 interaction, rounded to16|
|Runtime object list|1 slot|
|Allocator descriptors|A split can use1 more descriptor; fragmentation still matters|
|Header reference counter|1 unsigned-byte reference;256 wraps|
|Sprite reference counter|1 signed16 reference; existing cached sprite is reused|
|New header/sprite/texture assets|None **only if** those same assets are already resident; a new type in another map does not meet this premise|

No per-instance shadow texture is loaded because shadowGroup=0. General scenery
with shadowGroup!=0 calls load_texture per instance; TextureHeader also has an
unsigned-byte reference counter. The earlier208/224-byte block calculation alone
does not account for that counter. Source: objects.c:spawn_object,
obj_init_property_flags, get_object_property_size, init_object_shading,
init_object_shadow; textures_sprites.c:tex_load_sprite/load_texture;
include/structs.h:Sprite/TextureHeader/Object.

All58 candidate append/remove map streams pass rebuild/undo and the source-model
inflater checks headlessly. That demonstrates serialization/loading constraints,
not successful runtime spawning, collision or frame-budget behavior. Deletion
still needs its own reference/game check; a smaller map is not automatically safe.

## Why particle and snapshot measurements matter

`thread3_main.c:393` configures gameplay particle buffers as8,16,150,100,50;
the menu path at884 uses4,4,110,48,32. `particles.c:particle_allocate` stops at
configured-1 per kind. Their independent maxima sum to319 and193, respectively.
The usual emitted particle paths call `add_particle_to_entity_list`, which writes
into the **same512-entry object list**. Particle storage itself is allocated
outside the object subpool. These independent maxima are not measured simultaneous
peaks and must not be added to observed list counts (which already include listed
particles) to invent an allowance. Weapons, drops, racers, scene targets and
transitions add further lifetime-dependent demand.

## Read-only measurement tool

Open **File → ROM Budget and Project Changes → Runtime measurements**, then
**Load runtime snapshot…**. This accepts:

- Raw4 MiB /8 MiB RDRAM, big-endian, byte-swapped16 or word-swapped32.
- The inspected **BizHawk2.10 Mupen64Plus** `.State` ZIP carrier. Core.bin is
  bounded Zstandard data containing an `M64+SAVE` version0x10000 payload.
  Three independent64-byte executable anchors locate RDRAM; the reader does
  not assume the observed container offset. osMemSize selects4/8 MiB.

Fingerprint bytes come from the user's original Rev1 ROM at the local splat's
ROM0x1000 → RAM0x80000400 mapping. Anchors are spawn_object0x8000EA54,
mempool_slot_find0x80070F7C and gzip_inflate0x800C6778. Global addresses come from
`ver/symbols/symbol_addrs.us.v80.txt`, checked by tests. Headers/pools/caches are
validated before publishing a sample. Wrong executable, unsupported carrier,
truncation, cycles, corrupt pointers/counters and oversized inputs are rejected.
Raw/state readers do not execute code from the capture or write to its files.

Reports show both pools' occupied/free bytes, largest blocks and descriptors;
object list count; header/sprite/texture reference counts; cache holes/high-water
slots; and configured/live particles. Main-pool occupancy includes the reserved
object subpool allocation. Pending frees remain occupied. Code fingerprints do
not prove matching asset edits, game mode, vehicle or player count.

Multiple samples are grouped by loaded map-role IDs, with **observed** maxima
and minima. Up to64 samples are kept only while the report is open. Copy report
includes the observed summary and latest detailed sample. Nothing changes project
bytes/history or enables structural operations.

## Initial observed evidence, 2026-10-20

The two existing user BizHawk states were read offline; no emulator was launched.
Their names are labels, not trusted ROM identities. Both match all three Rev1
executable fingerprints and use map roles0/68 (the current header's Central Area
pair). Their captured conditions do not establish a controlled before/after test.

| State label | Object list | Object pool occupied/free | Largest free block | Pool descriptors |
|---|---:|---:|---:|---:|
|Rev1 edited QuickSave1|259/512|64,880 /23,184 bytes|16,784 bytes|306/512|
|RevA QuickSave1|264/512|65,200 /22,864 bytes|16,784 bytes|306/512|

Edited state SHA256: `76d8a822b3085a12dbc48c38b732fd25b70d46679c32786fe547ac4fbd6be6b0`.
Other state SHA256: `f6d90ae236a415d0781f3306d626834c2bff2823ba8f9505953215a6129004f3`.
Both decoded cores place the verified RAM region at0x1C0; the parser derives
this from anchors and tests a synthetic carrier at a different offset.
Ignored text-only evidence is in `artifacts/phase20-*-runtime.txt`.

These are actual snapshots, **not measurements of a whole race or worst case**.
Do not divide23 KiB by208 and treat the result as an approved object limit.
No capture has been used to approve any production structural operation.

The user subsequently confirmed that the corrected Lua helper ran in BizHawk
and its raw dump loaded in the editor. Capture `dkr-rdram-20261020-104151-1.bin`
(SHA256 `aa12f4add940ea787c0d08afd2354e98e145cb5b4b87e3a294e4decc0fcaaba8`)
is big-endian with map roles5/73:180 list entries,38,128 free object-pool bytes,
largest free block31,632 bytes,214 descriptors and8 live line particles. Game
mode/player count/activity were not reported. Its generated `.audit.txt` is
beside it under ignored artifacts. This is another observed sample, not a peak.

## Ancient Lake sample review, 2026-10-20

The user supplied five more raw captures, bringing this map pair to six distinct
8 MiB dumps. All validate as big-endian and match the three Rev1 executable
anchors. Map roles5/73 match Ancient Lake's header pair in the original ROM;
the engine role order is reversed relative to the header fields.

| Capture time (filename) | Listed objects /512 | Object-pool free bytes | Largest free block | Object-pool descriptors /512 |
|---|---:|---:|---:|---:|
|10:41:51 (earlier baseline)|180|38,128|31,632|214|
|10:53:48|192|33,696|31,632|228|
|10:54:13|185|35,136|31,632|227|
|10:54:34|179|36,816|31,632|222|
|10:54:52|179|36,816|31,632|222|
|10:55:13|180|36,816|31,632|222|

The observed minimum is32.91 KiB free in the object pool, with a30.89 KiB
largest block. The busiest captured list leaves320 slots unoccupied. Main-pool
free space stays at least363,136 bytes, with a329,584-byte largest block.
Header reference counts peak at50; texture references peak at101 versus84
in the first capture. Sprite/texture cache high-water slots stay40/396.
New samples have1–3 live sprite particles; the earlier sample has8 line
particles. They do not capture a peak of every particle type.

This completes the requested initial Ancient Lake baseline review. Observed
headroom supports further small-scale feasibility work; it does not establish
a universal addition limit, certify continuous race coverage or validate an
edited object count. Collection was requested during a single-player race with
weapon/particle activity; the dumps do not independently certify those conditions
or the loaded asset edits. No further random samples are needed for this review.

The narrow palm-top types are absent: header50/52 and sprite114/116 references
are zero in every sample. The two simple scenery candidates in Ancient Lake's
stock maps are solid BlueBerryBush placements, header43/sprite108, with a
per-instance shadow-texture reference. Other stock trees also fail the narrow
predicate. These samples cannot approve the narrower palm-top types in another
level, nor bypass the bush collision/shadow/reference checks. The next research
step was to resolve those costs for an exact same-map operation. The v1.13.2
source audit and restricted one-bush research command are documented in
[BUSH_EXPERIMENT.md](BUSH_EXPERIMENT.md). The rebuilt-map gameplay check remains
pending before Phase21 can enable the operation.

Ignored evidence: `artifacts/phase20-race-snapshot-report.md`,
`artifacts/phase20-raw-captures.json` and each dump's `.audit.txt`.
The report records all six SHA256 hashes, rechecked after parsing. Original ROM
SHA1 remains `6d96743d46f8c0cd0edb0ec5600b003c89b93755`.
No emulator run, test-ROM generation or change to an open editor was performed.

## Collecting more evidence in BizHawk

The easiest path is to save additional states during your own game tests, then
load them into the report. Keep different scenarios in separate files so later
quick saves do not overwrite the evidence. No test-ROM generation is needed.

An optional one-shot raw capture helper is
[`src/core/bizhawk_capture.lua`](../src/core/bizhawk_capture.lua). In BizHawk's
**Tools → Lua Console**, open that file while DKR is loaded. It reads the RDRAM
domain and saves a uniquely named `.bin` under this project's ignored `artifacts/`
directory, printing the path. Reload the script for another sample. It never
advances frames, changes input, writes game memory or manipulates save states.
BizHawk names its loaded Lua chunk `main`, so the helper uses an explicit
`OUTPUT_DIRECTORY` setting pointing to `D:/RomHacking/n64/dkr/artifacts`.
Change that setting only if moving the project; it does not depend on Lua debug
metadata or the emulator's working directory. Tests cover `main`, `=main` and
file-named chunks with all three supported read APIs.
It is tested in standalone Lua against stubbed read APIs; actual in-emulator
operation remains a user check. Its bulk read APIs follow the
[official BizHawk Lua reference](https://tasvideos.org/Bizhawk/LuaFunctions).

Useful coverage includes loaded/start-of-race conditions, a full race with
weapons and banana drops, heavy particle areas, supported multiplayer/vehicles,
level exits/restarts and relevant Adventure/cutscene contexts. Record the level,
game mode, player count and edits alongside samples. Sampling can establish
observed headroom for a particular test envelope; it cannot by itself prove
every possible future allocation or eliminate fragmentation concerns.

## Remaining gate

Before Phase21 enables an operation, its exact type/map/shared contexts need
resource and reference validation plus representative user gameplay results.
Positive additions still lack a justified runtime reserve. Broader creation,
cross-level templates, graph edits and arbitrary type conversion remain disabled.
The user-run one-bush research command checks the resident bush/header/shadow
references and captures' available208-byte block/split, without claiming a
future reserve or enabling production controls. Its audit also identifies the
separate257-pointer interactive-object stack array and preallocated scenery
shadow buffers; their future use cannot be inferred from the512-list bound.
The map-inflate check in STRUCTURAL_SAFEGUARDS.md addresses loading; it does not
resolve those gates.

REA's evidence/limitations workflow was applied to the offline carriers using
Python ZIP/Zstandard and source-derived readers; REA tools/CLI were unavailable.
No REA Evidence IDs or emulator execution are claimed.
