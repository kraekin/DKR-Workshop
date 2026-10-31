# Visual Add Objects catalog

Open **Edit → Add Object…** or **Objects → Add…**. The dialog shows the same
304 translated object types as before, now as artwork cards with a larger
preview. Search by name, ID, category or source behavior. The category selector
filters scenery, checkpoints, spawns, balloons, sound triggers and other types.
An empty search disables Add until an object is selected again.

Cards load progressively as they enter view. Models use textured thumbnails and
an interactive 3D preview: Alt + right mouse orbits, middle mouse pans, the wheel
zooms, and **Fit artwork preview** restores framing. Sprite previews assemble
their actual tiles, using the first nonempty frame. Texture-backed objects show
their referenced image. Artwork comes from the loaded original ROM and applied
project overlays; there are no bundled game images or disk thumbnail caches.

The preview is reference artwork. Helpers can use debug meshes/icons, vehicle
parts need runtime assembly, and game state can choose other variants. The
selected preview follows the chosen template's model/balloon fields. It does not
run behavior initialization, progression or physics. Unavailable artwork does
not prevent adding the object.

Choose **Target map**, XYZ and **Preferred template** or **Zeroed schema
defaults**, then click **Add object** or double-click a card. Preferred templates
retain the existing stock placement values. Zeroed defaults remain explicitly
untested schema entries. Placement, copied IDs/links, capacity validation and one
undo record use the existing object writer. Opening, filtering, orbiting and
canceling the catalog do not edit the project or move the main scene camera.

This update does not introduce favorites, presets or reusable groups.

Format evidence reuses `ObjectHeader` in local `include/structs.h` (0x78 fixed
header, artwork pointer 0x10, kind 0x53, signed count 0x55), `objects.c` header
relocation and spawn branches, existing ObjectModel/Texture/Sprite parsers and
the verified per-template entry schemas. No binary struct or project version
changed. Catalog thumbnails use a small read-only NumPy rasterizer; the selected
mesh preview uses the normal OpenGL renderer.
