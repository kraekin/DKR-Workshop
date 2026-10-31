# Phase20 — one-bush gameplay experiment (v1.13.2)

The user subsequently confirmed this experiment in-game. Three new RDRAM
captures match the exact map bytes, three208-byte bush allocations and expected
header/sprite references. The broader Phase21 tools were explicitly authorized
for all object types; see [OBJECT_EDITING.md](OBJECT_EDITING.md). This standalone
command remains available as the original restricted research profile.

This command prepares exactly one duplicate of an original Ancient Lake bush.
It is a restricted research export, separate from normal v6 projects and the
editor's production permissions. It does not enable Phase21 controls or certify
a general addition limit. The user generates and tests the experimental ROM.

## Run it

From `D:\RomHacking\n64\dkr`, first preview using the original ROM and the six
existing baseline captures:

```powershell
.\.venv\Scripts\python.exe -m src.core.bush_experiment `
  --rom "Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64" `
  --baseline "artifacts/dkr-rdram-20261020-10*.bin"
```

Preview builds and validates the experiment in memory and writes no files.
To generate it yourself, run the same command with an export destination:

```powershell
.\.venv\Scripts\python.exe -m src.core.bush_experiment `
  --rom "Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64" `
  --baseline "artifacts/dkr-rdram-20261020-10*.bin" `
  --export "artifacts/ancient-lake-one-bush.z64"
```

This creates the new ROM plus `ancient-lake-one-bush.z64.research.json` with
input/output hashes, the exact change and measured baseline. Choose a different
output name if either file already exists. There is no overwrite/force option.
Wildcards are expanded by the command, including quoted Windows paths. Keep
post-edit captures outside the baseline pattern or select baseline files explicitly.
The command accepts raw RDRAM or the supported BizHawk2.10 carrier and never
launches an emulator. It needs the original ROM; edited ROMs/projects are refused.

## What changes

The command reads map5, entry4 (`BlueBerryBush`, object ID73, header43,
sprite108) from the user's original ROM and appends one copy as entry98.
The original map's98 entries retain their byte order and exact entry bytes.
The duplicate retains all ID/size/flag/parameter bytes, including solidity.
Its position is128 units along positive Z from the original, with Y obtained
from the ROM track mesh. Original position is(-1074,60,-7262); the added bush
is at(-1074,59,-7134). The second stock bush is unchanged.

Map5 grows from2368 to2384 decoded bytes, including its16-byte header and
8-byte alignment. Staging needs2416 of12288 bytes. The compressed stream
passes the source-model in-place inflater. Compressed table/master offsets and
N64 CRCs are rebuilt using the existing bounded exporter. Output length stays
12 MiB, every other asset section and object-map stream is checked byte-for-byte,
and executable/bootstrap bytes are preserved. The output is reloaded and its
entry prefix, clone parameters and map header are checked before publication.

This profile has no template/type/count/map/position options. Every run begins
from the verified original ROM, so running it again cannot compound additions.
The normal editor continues to accept the original ROM plus ordinary projects;
do not open this edited ROM as a new editor base or weaken its identity check.

## Source audit

The authoritative references are under `research/Diddy-Kong-Racing`:

- `include/level_object_entries.h:27`:12-byte scenery entry; modelIndex, radius,
  angleY and solid, with no node/order/registration ID. Existing entries are
  never reordered by this experiment. The header catalog references map5 only
  from Ancient Lake (level5, map pair73/5); compiled/script contexts are not
  declared impossible merely because the catalog has no other reference.
- `objects.c:1941–2255`:spawn_object reuses the loaded header/sprite and reserves
  the inline data before one aligned object-pool allocation. Header43 has one
  sprite, zero attachments, zero emitters, zero light sources and zero misc assets.
- `get_object_property_size:10048`, `init_object_shading:2291`,
  `init_object_shadow:2381`, `init_object_interaction_data:2428`,
  `obj_init_property_flags:10458`:scenery reserves128 Object +4 sprite pointer
  +4 default behavior reservation +12 billboard shading +16 ShadowData +40
  interaction =204 bytes, rounded to208 by the16-byte allocator. Scenery does
  not request the separately registered collision-mesh block.
- `objects.c:891` increments the unsigned-byte header reference counter;
  `textures_sprites.c:940` increments the existing signed16 sprite counter and
  returns before loading its textures. Thus copying a resident sprite does
  **not** add a reference to each of its artwork textures.
- Header43 has shadowGroup1 and unk34=9. `objects.c:2381` calls load_texture(9)
  for each instance. `textures_sprites.c:455` interprets the clear high bit as
  a2D texture and increments its unsigned-byte counter if resident. The added
  bush therefore adds one reference to **2D texture9**, not3D texture9.
- `object_functions.c:113–183`:the stock solid=1 initializes an inline radius20
  interaction record. Hits bend the sprite and can play SOUND_TWANG. The particle
  branch requires particleCount>0, which is zero for this header. This behavior
  does not spawn another object. `audio_spatial.c:545–560` uses a preallocated
 40-point audio pool and safely declines a sound when full; audio playback and
  other sound-system resources still need an actual gameplay check.
- `objects.c:2790–2818` releases the shadow texture, sprite and header references
  on object cleanup before freeing its block. No custom scenery cleanup branch
  or per-placement external graph ID was found. The header's signed unk52 field
  is incremented on spawning; this source checkout has no consumer of that field.

With its original shared resources already resident, the predicted persistent
delta is208 object-pool bytes, one object-list slot, one interaction entry,
at most one descriptor split, one header43 reference, one sprite108 reference
and one2D texture9 reference. No new shared asset/cache slot allocation is
expected under that premise. Collision/audio/rendering work is additional to
this persistent allocation calculation.

## Additional limits found during this audit

`objects.c:4566` collects interactive nonparticle objects into a257-pointer
stack array, without a checked insertion bound. This is separate from the512
global object slots. For this command, the total captured list plus one must
fit257, which conservatively bounds its captured interactive subset. Future
interactive peaks remain unproven; total placed objects alone do not establish
the number collected by this function.

`tracks.c:259–263` preallocates four shadow buffers, each400 property records,
800 triangles and2000 vertices. Scenery uses buffers2/3; actors use0/1.
`shadow_update:3357` and `func_8002F440:3871` accumulate geometry from overlapping
track surfaces, so one new shadow does not imply a fixed number of triangles.
The existing runtime report does not measure those buffer peaks. This experiment
does not claim to prove shadow capacity or multiplayer/performance safety.
The buffers are already allocated; further shadow geometry does not itself
mean another persistent shadow-heap allocation at spawn time.

## Current baseline and user check

The six Ancient Lake snapshots have179–192 listed objects, at least33,696 free
object-pool bytes, a31,632-byte largest free block and at most228 descriptors.
Each has exactly two header43 and two sprite108 references. Texture9 varies
84–101. The CLI requires Ancient Lake roles, resident expected bush assets,
space for208 bytes and a descriptor split, and a spare texture reference.
These are observed-state checks, not an approved future reserve. The source
fingerprints do not certify the capture's loaded asset edits, mode or players.

1. Open the newly exported ROM in BizHawk and restart the game from that ROM.
   Do not restore an old state: it contains the old object map in RDRAM.
2. Enter Ancient Lake in single player. Find the added bush near the original
   at the coordinates above; check its image, ground placement and shadow.
3. Drive into it; compare its bending/collision/sound with the original. Race
   normally with weapons/particles, restart the track, then exit and re-enter.
4. Run the existing capture script after loading the edited level and again
   after those checks. The Lua Console prints the new file paths. Keep these
   separate from baseline captures and report any visible failure/crash.

After a fresh successful load, header43 and sprite108 should each have3
references. Under otherwise identical other usage, texture9 gains1, the list
gains1 and the object pool uses208 more bytes. Different gameplay moments can
change dynamic allocations and texture references, so pool/list differences
between unrelated frames are not an exact before/after measurement.

Passing this experiment supplies evidence for this one operation and scenario.
It does not automatically enable Phase21; operation/type bounds and the user's
gameplay results must be reviewed first. Normal project writer permissions and
the production structural allowlist remain unchanged.

## Automated verification

All853 headless tests pass in92.94s, including26 new profile/resource/publication
checks. The command's actual preview validates all six real captures and writes
no ROM. The source-model inflater reports31 bytes minimum unread-input gap and
6304/10240 bytes Huffman heap for this map. Compileall and CLI help pass.
Expected in-memory output SHA256 is
`b254874044f63f2a767c0ac39a2ba9bcb2f04bb761552e96fefb8f79d0d2530c`.
Text/JSON preview evidence and the full test log are under ignored artifacts.
The original ROM and six captures' hashes were rechecked unchanged. No emulator
was launched and no review ROM was saved outside temporary test fixtures.
