# Global Object Properties

Open **Edit → Global Object Properties…**. This separate window edits the shared
definitions used by placed objects, actors and game code. It starts on the
selected object's header when possible. The right-hand inspector stays unchanged.

For example, RubberTree's placed **object ID 78** resolves through the translation
table to **header 48**, whose original artwork is **sprite 113**. These are three
different IDs. Changing header48's scale or sprite affects all RubberTree uses,
including Central Area and Ancient Lake; moving one placed tree is still an
Objects-tab operation.

## Editing

1. Filter the 304 headers by internal name, header/object ID or behavior.
2. On **Properties**, double-click a value. Hover for units, ranges and runtime
   conditions. Integer fields accept decimal, hexadecimal or binary values.
3. On **Artwork**, choose an existing asset for each retained slot. You can type
   its ID or use the searchable dropdown; known owning definitions are named.
   The existing model type selects the correct model/sprite/texture namespace.
4. **Known uses** lists translation aliases, placed instances/maps, affected
   levels and attachment parent headers. Dependencies include animation actor
   targets, attachment chains and level skyboxes. Compiled spawns, racers and
   menu/cutscene code can add uses not represented by placed maps.
5. Edit additional headers if desired. Asterisks mark pending drafts. Review
   **Pending changes**, then click **Preview pending changes** for compatibility
   validation and the exact combined ROM budget/report.
6. **Apply pending definitions** commits all drafts as one shared undo step.
   Closing the window discards unapplied drafts. **Reset this draft** removes
   only the current pending draft; **Restore original definition (draft)**
   stages its original ROM values for review and Apply.
7. Save the `.dkrproj` and export an edited ROM through the normal File menu.
   The original ROM remains read-only. The user performs gameplay testing.

Undo/redo refreshes the window and viewport. It is disabled inside the window
while drafts are pending; reset/apply/discard those drafts first. A preview is
invalidated by further edits and cannot be applied after the project changes.

## Supported properties

| Property | Stored field | Meaning / preview behavior |
|---|---|---|
| Base scale | f32 at0x0C | Shared initial scale; per-entry size and behavior code can multiply or override it. Supported sprite/model previews refresh after Apply. Editor range0.001..64. |
| Draw distance | s16 at0x4E | Camera distance in game units;0 skips this cutoff. Fade begins at80%; four-player rendering halves the distance. Other game culling still applies. Editor preview ignores this cutoff. |
| Ambient / diffuse | f32 at0x28 /0x2C | Used by shaded3D initialization; ambient0..1, diffuse below2. Game code can override them. |
| Light RGB / intensity | four u8 at0x3A..0x3D | RGB/intensity override when intensity is nonzero. These bytes have known consumers despite the older tool's unknown labels. |
| Light angles Y/Z | s16 at0x3E /0x40 | Signed binary angles;65536 units per revolution. |
| Directional point lighting | u8 at0x71 | Boolean game lighting mode; enabling requires a shaded3D behavior, lit models and no attachment-only initialization path. |
| Shadow scale | f32 at0x04 | Scale for an existing shadow; editor range0..64. Does not enable a new shadow group/allocation. |
| Shadow bottom / top | s16 at0x46 /0x48 | Projection bounds relative to object Y; bottom must be below top when edited. |
| Shadow cutoff / fade start | s16 at0x4A /0x4C | Single-player cutoff and inner fade distance. A fade start at/above cutoff results in a hard cutoff. |
| Water-effect scale | f32 at0x08 | Scale for an existing behavior water effect; editor range0..64. Does not create an effect or water group. |
| Artwork IDs | BE u32 entries at pointer0x10 | Existing3D models, sprites or encoded texture references, according to the retained type. |

Lighting, shadow and water rendering remain the editor's existing approximate
previews; editing these fields saves game properties without claiming a matching
game lighting/shadow simulation. A property may have no visible effect for a
behavior that does not consume it. Scale changes can also affect gameplay sizes.

## Artwork compatibility and retained data

Artwork reassignment changes an existing slot, not the referenced asset itself.
Use the Texture & Sprite Browser to edit an image's pixels separately.

- Sprite replacements retain at least the original frame count, with validated
  sprite/tile/texture references. Billboard and vehicle-part sprite types keep
  their original type and number of slots.
- 3D replacements retain the animation clip count and generated-normal lighting
  layout, and provide at least the original attachment and collision-sphere
  capacities. Target mesh/animation data and attachment vertex indexes are
  validated. This preserves those data capacities; model shapes, animation
  meaning, scripted vertex assumptions and whole-scene RAM usage still need a
  game test. Swapping a model can also change its model-based collision.
- Special texture references retain at least the original frame count. Their
  encoded IDs use bit0x8000 for3D textures; other IDs select2D textures.
- Behavior, model type, slot/attachment/particle/light counts, allocation flags,
  pointers, internal names, attachment/particle/light/misc arrays and unknown
  bytes stay byte-exact. **Protected data** shows these values and the raw asset
  read-only. No arbitrary raw-header writer or behavior conversion is enabled.

Header storage and its object-pointer array size do not grow. Different artwork
can nevertheless load different texture/model resources, and draw/shadow changes
can increase runtime work. A zero ROM growth report is a storage result, not a
claim that peak game RAM, object pools or rendering costs are identical.

## Local source evidence

All game-format evidence comes from
`research/Diddy-Kong-Racing`, targeting USA Rev1 (`us.v80`):

- `include/structs.h:798–867`: fixed ObjectHeader0x78 bytes, followed by pointed
  arrays and retained opaque data. The stale duplicate0x48 comment on
  `shadowBottom` is corrected by field order: bottom0x46, top0x48.
- `src/objects.c:891–920`: header assets load uncompressed from section34 with
  offsets from section33, then five pointers are fixed up in RAM. The512-entry
  translation table in section35 is unchanged.
- `src/objects.c:1934–2147,2290–2418`: initial scale, model/sprite/texture loading,
  behavior allocation, shading, attachments and existing shadow/water effects.
- `src/objects.c:3480–3640,7879–7899,10458–10594`: lighting and attachment
  rendering, angle initialization and the shaded behavior cases.
- `src/tracks.c:2328–2349,3421–3461,3565–3566`: distance cutoff/fade,
  shadow cutoff/inner fade and vertical bounds.
- `tools/dkr_assets_tool_src/builder/buildTypes/buildObjectHeader.cpp`: BE fields,
  fixed model/count arrays and tail layout. Runtime consumer names take
  precedence over older builder labels for lighting/unknown fields.

## Persistence and verification

Projects containing global definitions use **version13**. They store section34
byte overlays with original asset hashes; loading revalidates the full protected
layout, field values and changed references. Versions1–12 keep their former
writer permissions and cannot install global-header overlays. Version13 also
supports course names, imported tracks/artwork, structural objects and earlier
edits. The fixed-length writer retains section33/35 and untouched assets.

Checks cover all304 original headers, every protected byte in a representative
header, finite/ranged fields, valid/incompatible artwork, known dependencies,
cancel/refusal/stale preview, one-step history, cache refresh, legacy permission
refusal, v13 reopening and in-memory ROM isolation. Native checks exercise the
real Edit action/modal, numeric editors, sprite/model assignments, preview/Apply,
undo/redo, draft discard, project reopen, retained camera/object count and clean
RTX4060 OpenGL3.3 rendering. No persistent review ROM or emulator run is generated.

Final gate: **1,459 tests pass in253.12s**, including50 global-object tests;
129 focused artwork/image checks pass. Normal module launch reports OpenGL3.3
on the RTX4060 with4x MSAA and no errors. User gameplay review is next.
