# Custom-course finishing and sharing

## Generate a minimap

Select the course and open the inspector's **Minimap** panel, then **Generate
minimap from track…**. Choose the existing sprite canvas, all visible collision
surfaces or one driving surface, rotation and padding. The slope filter excludes
steeper faces; hidden/non-collision batches and vertical/degenerate faces are
excluded. Select **Generate preview**.

The preview uses quantized pixels and the game's marker projection. Switch
between Adventure 1 and Adventure 2 to inspect mirrored alignment. Review known
shared image uses before **Apply artwork + alignment**. Artwork and projection
fields form one Undo/Redo step. **Export preview PNG…** saves the generated image
without changing the project.

Generation uses the current track, including imported geometry and applied edits.
It fits selected geometry into an existing fixed-size sprite; it does not allocate
new sprites or enlarge their tiles. Overlapping tile layouts, unusable padding,
gaps intersecting the generated image or empty face selections are rejected.
Use a different canvas/surface selection when needed. Other users of that sprite
or its image tiles also see the replaced artwork. Existing minimap-settings
Revert restores settings only; use Undo or Texture Browser revert for artwork.

## Batch images and animation sheets

Open **Edit → Texture & Sprite Browser / PNG…**, select multiple rows with
Ctrl/Shift or filter the list, then **Batch export / import…**. Choose selected,
visible filtered or changed assets in the current category. Export a new package
folder, optionally using **Animation sheets**. All nonempty frames are included;
empty sprite frames keep their original indexes in the manifest.

Keep `images.json` with the PNGs. Separate-frame files carry PNG orientation
metadata; sheets lay independently oriented frames left to right. The manifest
retains IDs, frame rectangles, orientation and exported-pixel identities. Editing
software may strip PNG metadata; the manifest still supplies orientation. Retain
dimensions and sheet rectangles, and do not edit manifest identities.

Choose **Review images.json…** to stage a package. Inspect the decoded N64 result,
changed-pixel/quantization report and shared uses, then **Apply imported package**.
No project bytes change before Apply. The entire package is one Undo/Redo step.
Unedited frames remain byte-identical. Stale exports/previews, conflicting edits
to shared tiles, unsupported dimensions/formats and paths outside the package
are rejected atomically. Re-export a package after changing its source assets.
Existing palettes, animation lengths and sprite layouts remain protected.

## Alternate routes and lanes

Open **Edit → Route finishing / alternates…** or the matching Routes-panel button.
Start with at least four main checkpoints, authored in Course Builder. Choose a
checkpoint set and an inclusive main-index range, then **Create paired branch**.
Each alternate replaces the main checkpoint at the same index. For a branch
crossing CP0, create the end and start ranges separately.

Select an alternate row, enable **Click road to place selected alternate**, and
click the intended road. With that option off, select/drag alternate handles or
edit XYZ in the table. Main checkpoints stay protected in this window. **Undo
branch edit / Redo** covers branch additions, removals, placement and movement.
Set switching retains branch rows; **Apply current checkpoint set** applies the
selected set. Unapplied drafts are discarded when closing the window.

Optionally align alternate headings and generate four evenly spaced AI lanes.
Width is in game units; conversion must fit each checkpoint's existing signed8
offset range. Height fitting chooses nearby road layers and refuses ambiguous
or out-of-range results. Existing lane heights/behavior selectors remain unless
their respective options are enabled. Readiness notes can focus their checkpoint
when double-clicked. These are authoring diagnostics, not racer AI simulation.

Apply performs the existing structural/shared-map/reference/ROM budget checks,
then stores one project Undo/Redo transaction. The 60-checkpoint limit includes
main and alternate entries. Unknown bytes, aliases, identity provenance and level
vehicle-to-checkpoint-set mappings retain their existing protections.

## Export a BPS or xdelta patch

Choose **File → Export ROM patch (BPS / xdelta)…** and select the format. Workshop
builds the validated edited ROM in memory, encodes a patch against the original
big-endian ROM, verifies reconstruction and writes the patch atomically. It
does not write an intermediate edited ROM, mark the project saved or add history.
Original-ROM path protection and normal export refusals apply.

Distribute the patch with its required base identity: **Diddy Kong Racing USA
Rev 1 / USA 1.1 `.z64`**, SHA-1 `6d96743d46f8c0cd0edb0ec5600b003c89b93755`.
Even when Workshop opened `.v64` or `.n64`, patches require the normalized `.z64`.
Save your `.dkrproj` separately to resume editing.

BPS1 includes source, target and patch CRC32 checksums. The xdelta export is
VCDIFF using the default ADD/COPY instruction table and xdelta3's target Adler32
checksum, without a secondary compressor. Both encoders are implemented in
Python; no external patcher is bundled or required to export. Patch consumers
can use standard BPS/xdelta tools. Format references:
[Floating IPS](https://github.com/Sir-Walrus/Flips),
[RFC 3284](https://www.rfc-editor.org/rfc/rfc3284.html),
[xdelta](https://github.com/jmacd/xdelta).
