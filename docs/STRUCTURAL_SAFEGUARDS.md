# Structural feasibility and safeguards — Phase 20

Current scope: after the successful one-bush gameplay check, the user explicitly
requested all-type experimental tools. Phase21 is documented in
[OBJECT_EDITING.md](OBJECT_EDITING.md). Its known binary/resource bounds remain;
the type/reference allowlist described historically below is superseded.

v1.13.0 adds a **read-only Object capacity audit** tab to **File → ROM budget
and project changes**, plus an isolated headless research foundation. It does
not add creation, duplication, deletion, reordering or type-conversion controls.
Normal projects remain version 6. Structural production operations are disabled.

## Findings from the local Rev 1 source

Only `research/Diddy-Kong-Racing` and the verified original USA Rev 1 ROM were
used. No offsets, sizes or runtime reserves were guessed.

| Resource | Source-backed bound / meaning |
|---|---|
|Map workspace|`objects.c:44,978–1014`: 0x3000 / 12,288 bytes per map role|
|Compressed staging|For decoded length U and stored table span C, the loader places input at `U - C + 0x20`, ending at `U + 0x20` relative to the allocation|
|Necessary address bounds|`U + 32 <= 12288` and `C <= U + 32`; U includes the 16-byte map header and decoded padding, C includes stored entry padding|
|Maximum decoded length under that bound|0x2FE0 / 12,256 bytes, at most 12,240 entry bytes before alignment|
|Entry serialization|Common `>BBhhh`: nine-bit ID is low byte plus size bit7; size is low6 bits; bit6 is preserved. Entries retain source schema lengths. Map payload length is BE u32; bytes4–15 are preserved; file aligns to8 bytes|
|Shared object pool|`objects.c:46,717–763`: 0x15800 / 88,064 data bytes. Shared ObjectHeader assets are allocated in this same pool by `load_object_header`|
|Allocator metadata|`memory.h:MemoryPoolSlot` is0x14 /20 bytes.512 descriptors add10,240 bytes separately: subpool allocation total0x18000 /98,304 bytes|
|Allocator behavior|`memory.c:45–93,123–171,513–547`: data allocations align16; best-fit/free fragments consume descriptors; allocation refuses when `curNumSlots + 1 == 512`. Even a favorable unfragmented run admits at most510 live allocations, including headers and object blocks|
|Object list|512 total runtime slots; not512 extra/placed objects. Overflow is logged after insertion, not safely refused before the write (`objects.c:2217–2220`) |
|Object blueprint|0x800 /2,048 bytes for assembling one object before copying its block into the subpool|
|Object base|0x80 /128 bytes: fields through0x78 plus8-byte ObjProperties. The0x630 comment above Object in structs.h is stale; `object_properties.h` explicitly describes the8-byte union. Do not use that comment as sizeof(Object)|
|Other inline blocks|`ObjectInteraction`40 bytes; `ShadowData`16; `ShadeProperties`48. Billboard shading reserves12 due to `(returnSize & ~3)+4` |
|Property reservations|`get_object_property_size` returns `(size & ~3)+4`, including4 when there is no behavior block. WeaponBalloon reserves12, Banana16 |
|Header references|Unsigned-byte counter (`objects.c:263,891–928`);256 references wrap to zero. Placed-count checks alone cannot reserve dynamic references|
|Other caches|`object_models.c:16`:70 model assets. `textures_sprites.c:10–14`:700 textures,100 sprites,20 palettes. Dynamic/transitive asset use and main-heap bytes remain separate constraints|

The address tests are **necessary**, not a proof that every new DEFLATE stream
is safe for the game's overlapping in-place inflater. v1.13.1 adds the per-stream
source-model check described below. Address checks or zlib decompression alone
are insufficient.

The builder evidence is `tools/dkr_assets_tool_src/builder/buildTypes/buildObjectMap.cpp`
and `fileTypes/levelObjectMap.hpp`: a16-byte header, payload byte count and8-byte
decoded alignment. The existing Rare stream/table rebuild and16-byte stored
alignment remain unchanged.

## Measured original-ROM inventory

| Measurement | Result |
|---|---|
|Object maps|138; slots81 and99 have no stream/header and remain vacant|
|Tightest staged map|Map91: decoded10,440 bytes, stored3,584 bytes; required10,472 of12,288, leaving1,816 bytes under the address bound|
|Largest current header-referenced pair|301 entries, level20 Windmill Plains|
|Largest all-entry allocation baseline|48,032 bytes, level0 Central Area; includes aligned128-byte base + model pointers + minimum4-byte property reservation, plus distinct shared headers|
|Largest single-map placed references to one header|197, below the unsigned-byte wrap threshold, with no dynamic reserve claimed|
|Narrow research templates|206 placed billboard scenery entries.177 have208-byte object blocks;29 have224-byte blocks. Shared headers/sprites/textures are additional|
|Known graph findings|Four existing Snowball Valley alternate-checkpoint pairing findings, also reported by the existing route diagnostics; no automatic repairs|

**48,032 is a baseline demand, not measured peak usage and not “40,032 bytes
free.”** It omits larger behavior blocks, inline effects, attachments, racers,
cutscene targets, weapons, dropped bananas, allocation lifetimes/fragmentation,
model/sprite/texture memory and other runtime state. Some entries are filtered
by game mode or freed during initialization. Static entry counts are not a
complete runtime model.

The audit reads both map roles for every current level header, including a map
used twice. Shared header allocations are counted once per context; references
and entries count both roles. Maps without a current header use are not declared
unused: compiled/scripts may refer to them.

## Conservative templates and reference policy

The researched behavior set is ordinary scenery, bananas and weapon balloons.
A research template currently needs lossless bytes, billboard model type,
existing model IDs and **zero attachments, emitters and light sources**. Scenery
model and balloon-type selections must be valid. In stock data, only206 scenery
placements meet that complete narrow predicate. Many trees, every placed banana
and weapon balloon encountered here have an emitter and are therefore excluded
from this subset. This is not a claim that their emitter systems cannot be
supported later.

Known consumer evidence:

- `object_functions.c:obj_init_scenery/obj_loop_scenery`: scale, collision/bending,
  sound and optional emission. Simple billboard blocks can be calculated exactly;
  dynamic emissions need additional budgets.
- `obj_init_banana/obj_loop_banana`, `racer.c:drop_bananas`: placed/dropped states,
  particles and runtime spawns. A lower placed count does not bound live drops.
- `obj_init_weaponballoon/obj_loop_weaponballoon`: respawning scale, pickup and
  emission; acquired weapons spawn elsewhere. Script targets, attachments and
  racers also allocate dynamically through spawn_object.
- AI adjacency links are global loaded-node IDs, not entry ordinals. Checkpoints
  have set/order/alternate relationships. Cinematic entries share actor/channel
  groups and can refer to other actors. Progression objects have additional
  IDs/counters. Known references are evidence to block an operation; finding
  none is not proof that compiled/unknown references are absent.

The isolated draft refuses append/remove for all graph, progression, unknown,
and unaudited templates. Reorder permits only exchanging eligible entries;
protected entries cannot be moved by that operation. It never renumbers node IDs,
changes object types/aliases or creates graph nodes. No research template is yet
approved for a production structural operation.

## Headless foundation and migration design

`src/core/structure.py:StructuralDraft` is separate from EditSession and has no
file-save/UI integration. It exercises append from an existing template, remove,
candidate-only reorder, reversible whole-map snapshots and deterministic
rebuilding. New bytes come from the supplied user's source ROM/project, never a
bundled proprietary template.

Stable identities are independent of the current entry ordinal:

- Original: `base:<map>:<original index>:<original entry SHA1>`.
- New: `new:<map>:<monotonic serial>`. Undo/branching never reuses a discarded ID.
- Template provenance stays attached to each entry. Research notes are keyed by
  stable original identity; duplicates do not inherit claims about another object.

Existing v1–6 projects first use the normal gated project loader, then migrate
to a draft from their current overlay. Original identities survive byte edits;
the source signature and decoded-map hash pin the exact project snapshot.
The separate `dkr-structural-research` version1 document records template
identities and positions, not arbitrary binary patches. It cannot be loaded as
a normal `.dkrproj`. Reopen requires the matching source session/project.
Unknown/reserved bytes and alias/size flags come from its verified templates.
Protected graph records cannot be removed, reordered or changed by this format.

The draft's `experimental_rom_bytes()` returns **only in-memory experimental
bytes**, checks necessary map/list/header-reference/pool/descriptor bounds across
every affected shared level, and uses the same bounded ROM assembler/checksum
logic as the normal writer. It does not certify gameplay or runtime resource
headroom. A changed source project rejects the draft export. No review ROMs were
saved and no emulator was launched.

Normal EditSession now explicitly checks map byte length/header/padding/count
and entry ID/size flags before installation/export. It refuses structural
research fields/documents, while ordinary existing-entry edits remain available.
Modified maps also undergo the loader address-bound checks in export preflight.

Future production migration needs a separately reviewed project version,
selection/filter/history/research integration using stable identities and
validated operation/type gates. The draft format is an experimental design,
not a silent upgrade of users' existing projects.

## Verification and remaining gate

Headless checks cover all138 no-edit map round trips, header/unknown/alias flags,
alignment, append/remove/reorder, exact undo/redo, no identity reuse, imports of
project versions1–6 with edits/notes, document tampering/refusals, known graph
references, actual capacity rejection with atomic state, shared roles, other-map
and other-section preservation, original ROM length/checksums and experimental
export reload in memory. Native checks exercise the actual File report action,
both read-only tabs and Copy, clean project state, camera preservation, ordinary
edits/undo and unchanged compact toolbar rows.

**No safe additional-object allowance has been proven. Production creation,
duplication, deletion and reorder remain disabled.** Before Phase21 enables any
operation, establish the missing resource/inflate/reference bounds and obtain
representative user in-game results for that exact operation/type. No Phase21
UI was implemented. Final test results are in compact STATUS.md.

## v1.13.1 — source-model inflater and runtime measurements

`compression.py:audit_inplace_rare` follows gzip.c's Huffman table construction
and hasm/gzip_asm.s's bit refill, root/subtable lookahead, literal, forward-match
and stored-copy order. Each read/write is checked against staged input and the
declared output. Table allocations include link entries, accumulate within a
block and reset between blocks; usage must stay within0x2800 bytes. Independent
zlib output must agree. This models source accesses; it does not execute MIPS.

The game has no zero-length guard in its stored-block copy loop, so otherwise
valid DEFLATE with an empty stored block is refused. Its huft_build leaves the
`n = x[g]` correction commented out; incomplete trees containing zero-length
symbols can read uninitialized v[] entries during construction. Those streams
are refused rather than certifying them with a cleaned-up Python algorithm.

All136 nonempty original maps and their ordinary recompressed versions pass;
the minimum unread-input gaps are15/16 bytes, and maximum Huffman usage is7080
of10240 bytes. A synthetic valid multiblock stream that fits the address bounds
but overwrites unread staged input is rejected. Fixed/dynamic/stored blocks,
short forward back-references and valid-zlib/game-unsafe cases have headless
tests. Modified production-map exports and research drafts run the check before
publication. Untouched ROM streams remain byte-identical. This does not change
the normal v6 project's structural writer permissions.

The source comparison received a separate read-only review; its incomplete-tree
finding was incorporated before validation. The narrower58-placement decoration
subset and read-only RDRAM/BizHawk measurements are in
[RUNTIME_CAPACITY.md](RUNTIME_CAPACITY.md). Two historical user states supply
actual initial observations, not guaranteed reserves. Runtime/reference/game
gates remain open; production structural operations are still disabled.

The v1.13.2 source audit adds two constraints previously absent from the static
object-pool/list inventory: `objects.c:4566` collects interacting nonparticle
objects into an unchecked257-pointer local array, and `tracks.c:259–263`
preallocates400 shadow records,800 triangles and2000 vertices per buffer.
Shadow geometry demand depends on intersected track surfaces. These limits
must be considered separately from512 shared object slots. See
[BUSH_EXPERIMENT.md](BUSH_EXPERIMENT.md) for the exact208-byte resident-bush
delta, per-instance2D shadow-texture9 reference and restricted user-run export.
This command exposes one Phase20 experiment; it does not expand the production
allowlist or certify those dynamic/rendering bounds.
