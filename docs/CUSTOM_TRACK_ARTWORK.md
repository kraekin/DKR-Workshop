# Custom-track artwork

Current track OBJ exchange (v1.25.5): one OBJ unit is100 game units. Use Blender
import/export Scale1 and suite import multiplier100. UVs, images and driving
surfaces are unchanged. Historical sample files on this page retain their raw
coordinates and use explicit suite import multiplier1.

For the complete Blender authoring and export workflow, see the
[Blender track guide](BLENDER_TRACK_GUIDE.md).

Choose **Geometry → Import OBJ…** and keep the OBJ, referenced MTL files and PNGs
together. The importer finds `mtllib`, `newmtl` and `map_Kd` automatically. On
**Materials**, each named material can use **New PNG / color** or an existing
track texture slot. New artwork is appended as dedicated 3D assets, preserving
every existing texture ID and its artwork. Levels sharing the replaced geometry
still share the resulting track; affected levels appear in the report.

Select a material row to compare **Source PNG** with **N64 result**. Choose PNG
manually to resolve a missing/unsupported map, or select a ROM slot. Width and
height use8/16/32/64 powers of two; resizing is nearest-neighbor. RGBA16 stores
5-bit RGB and binary alpha. RGBA32 preserves8-bit color/alpha. All choices must
fit the N64's4 KiB TMEM:32×32 RGBA32 and64×32 RGBA16 are examples that fit;
64×64 RGBA16 does not. The preview explains rejected combinations before Apply.

**Opaque** forces alpha255. **Cutout** uses a128 threshold and the game's cutout
flag; choose it for holes with binary alpha. **Blend** requires RGBA32 and uses
the transparent render pass. Alpha changes the picture, not the collision mesh.
Clamp U/V prevents repetition on that axis; unchecked axes wrap. Each new
material starts with **Default / road** as its driving surface, adjustable
independently of the image. Existing-slot materials can inherit their surface.

MTL `Kd` and `d`/`Tr` are baked into the converted PNG's RGB/alpha. Materials
without an image use a solid diffuse color. PNG alpha can be reused by the
exporter's `map_d -imfchan a` when it names the same diffuse image. Separate
opacity maps and map transforms/other map options are rejected for new artwork;
combine those effects into a PNG or choose a ROM slot. Diffuse-map `-clamp on/off`
is supported. Lighting/specular settings are not recreated, and normal/bump/
other maps are reported as unused. Only local single-frame PNGs are read;
sidecars do not fetch URLs or network shares.

Change any setting, then **Build preview**. Compilation runs on a worker and
displays converted textures on the mesh, alongside the original object/path
overlay. Cancel discards the staged result, including its new artwork. **Apply
track import** commits geometry and new textures together as one undo step.
Failures preserve the project and history. Existing single-segment mode remains
available for ROM-slot-only imports; dedicated artwork uses Automatic/Spatial.

Save the project and export a new ROM through the normal File menu. New artwork
also appears in the Texture & Sprite Browser and existing material selectors;
its pixel/timing edits retain the same fixed header/dimensions. Reimport the
authored mesh to change dimensions/format. Browser PNG exchange preserves the
dedicated image's original row order. Stock 3D assets retain their earlier
upright editing flip; OBJ/MTL exports use PNG rows paired with OBJ UVs.

Identical canonical custom textures reuse an existing dedicated ID. Different
driving surfaces can share the image through separate TextureInfo slots.
Restoring stock geometry keeps appended assets and their stable IDs in the
project; undoing the original combined import removes its additions. No automatic
renumbering/garbage collection is performed. Existing stock PNG replacement is
still a shared edit and is distinct from these dedicated imports.

## Source evidence and storage

All binary rules come from the matching local decomp:

| Data/consumer | Verified behavior |
|---|---|
| `include/structs.h:102–140` | TextureHeader32 bytes: width0, height1, mode/format2, instances5, BE flags6, frame count bytes18/19, BE stride22, compression29 |
| `include/structs.h:565–571` | TextureInfo8 bytes: u32 ID, width/height/format, signed driving surface |
| `builder/buildTypes/buildTexture.cpp:45–133` | Header/flags, instance1, frame count01 00, aligned stride, PNG rows and optional compression |
| `textures_sprites.c:378–405` | 3D/2D table lengths discovered through FFFFFFFF; tables loaded dynamically |
| `textures_sprites.c:455–583` | 3D ID flag8000 +15-bit index;700 live cache entries; uncompressed allocation = entry size +96 bytes per frame |
| `textures_sprites.c:1450–1605`, `include/PR/gbi.h` | Power-of-two wrap masks, RGBA16/32 load blocks, cutout/blend and TMEM sizing |
| `buildModel/objModel.cpp:162–240` | OBJ material library and diffuse-map lookup; UV texel dimensions are assigned by the material |

New assets are canonical uncompressed static RGBA textures with32-byte headers,
zero runtime pointers/unused bytes and an aligned frame stride. This avoids
introducing another in-place decompression path. No palettes, new animation
frames or changes to existing asset headers are enabled. ROM data/table sections
are2/3; offset tables gain entries ahead of the retained FFFFFFFF terminator and
padding. Old entries and unrelated sections retain their bytes. Master section
offsets, alignment and checksums use the existing bounded exporter.

The editor allows at most128 dedicated assets per project (an editor bound),
255 named materials/track slots,16 MTL files of at most1 MiB each,16 MiB per PNG
and16 megapixels of decoded material input combined. IDs remain below8000.
Each texture is at most4 KiB of texels. The report includes actual ROM/table
growth and each new texture's allocation cost. The texture table itself grows
by4 bytes per added offset plus section alignment and is resident at startup.
The700-entry cache is a live residency limit, not the total ROM texture count;
objects/effects and other textures share it and the general memory pool. The
importer does not increase those limits or claim whole-scene peak capacity.

Projects with dedicated artwork use version11, embedding canonical baseline
images and any later pixel edits. Files do not depend on external PNG/MTL paths
after Apply/save. Versions1–10 retain their original writer permissions.
See [PROJECT_FORMAT.md](PROJECT_FORMAT.md).

## Ready-made sample and review

Use `artifacts/samples/ancient-lake-custom-artwork/ancient-lake-custom-artwork.obj`.
It is the previously tested segmented sample with original procedural checker
road/grass and purple brick artwork, plus its MTL and three PNGs. Select Ancient
Lake, keep geometry/texture defaults, set Grass surface to Grass and Wall to Stone,
then build and apply. It creates three32×32 RGBA16 assets:6,240 ROM data bytes
and6,528 bytes of texture allocations if all three load, plus table growth.
Test textures/UVs, the whole course and lap completion; compare a stock track.
The user exports their ROM and performs gameplay review. Automated verification
uses in-memory ROM assembly and owned native editor windows only.

Automated/native gate:1,261 full tests pass in312.25s, followed by the affected
final parser/refresh checks. Native RTX4060 OpenGL3.3 passes chooser/preview,
format/alpha/clamp/TMEM refusal, surfaces, cancellation, atomic history, browser
edits, v11 reopening, OBJ/PNG export and narrow inspector. Sprite refresh compares
resource owners and transforms without ambiguous NumPy array equality. The
original ROM hash remains unchanged.

User gameplay review, 2026-10-20: all new textures appeared correctly, and the
user completed the track without reported issues. The representative custom-artwork
gameplay gate is complete.
