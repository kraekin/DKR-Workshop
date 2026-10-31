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

Open **Edit → Course Builder…** or the Routes inspector's **Course builder…**
button. One window has **Checkpoints & branches**, **AI lanes** and **Start grid**
tabs sharing the same preview, draft Undo/Redo and **Apply course**. The set
selector above the tabs defines the checkpoint set being edited; grid changes
join that transaction. The inspector remains available for quick existing-object
lane/connection edits. There is no separate Route Finishing window.

On **Checkpoints & branches**, draw/edit the main sequence. Under **Alternate
branches**, choose an inclusive checkpoint range and **Create paired branch**.
Select an alternate, then **Place alternate on road**, edit XYZ or drag its
handles. Pairing follows the main point through reordering, reversal and CP0
changes, including newly drawn unsaved points. Removing a main point also removes
its paired branch and manual lane adjustments from the draft; Undo restores them.
For a branch crossing CP0, add the end and start ranges separately.

On **AI lanes**, generate evenly spaced lanes and optionally fit heights to
nearby road or reset behavior selectors. Choose a checkpoint/alternate in the
individual-adjustment selector or select its marker, then edit the four lanes'
lateral, height or behavior values. Individual adjustments override generation;
**Use generated / stored values for this checkpoint** clears those overrides.
All of these operations remain drafts. The AI tab shows all four lanes; the
preview selector also offers individual lanes or the centreline.

On **Start grid**, place/aim/fit the eight racers as before. Readiness and ROM
budget review cover the combined route, branches, lanes, grid and cleanup. Apply
performs the existing structural/shared-map/reference/export checks and commits
one project undo step. Closing the builder discards all unapplied changes.
Switching sets preserves their draft rows; Apply targets the selected set and
requested grid/cleanup. **Copy this route to every level vehicle set** replaces
the other mapped routes and copies branches and requested lane edits too.

Existing image/patch workflows remain separate from this authoring draft. Game
bounds still apply: at most60 main+alternate checkpoints per set, signed8 lane
offsets and fixed header mappings. Height fitting refuses ambiguous/missing road
layers or unrepresentable offsets. Unknown bytes and stable entry provenance
remain protected. Diagnostics do not simulate racer AI or gameplay.

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
