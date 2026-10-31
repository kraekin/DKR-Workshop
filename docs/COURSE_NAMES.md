# Course names

Open **Edit → Course Names…**, at the bottom of Edit after the separator.
**Texture & Sprite Browser / PNG…** is beside it in that menu. Both tools have
their own windows; neither adds controls to the right inspector.

1. Load the original USA Rev1 ROM or an existing project. Select/search a course
   in the names window; all65 existing levels are included, with stable IDs.
2. Edit English, German and/or French. You may stage several courses before
   applying. Changing the selected row retains their drafts. Japanese text is
   shown read-only, and its original encoded bytes are preserved.
3. **Preview name changes** validates the drafts and shows their changes, exact
   ROM budget and the total name block loaded in game RAM. Apply stays disabled
   until a valid preview is built. Editing a field invalidates the preview.
4. **Apply pending names** commits all staged courses as one project undo step.
   Editor labels, translated-name search, level details and the viewport caption
   refresh without changing the selected level, camera, geometry or objects.
5. Save the project and export a ROM normally. **Undo project edit / Redo project
   edit** share the main history and are enabled when there are no pending drafts.
   **Restore original names (draft)** stages the selected course's original three
   Latin names. **Reset pending for this course** discards just that course's
   draft. Closing the window discards unapplied drafts, retaining applied edits.

Names are limited to63 printable ASCII bytes. A changed name must have glyphs
in the game's FunFont banners, SmallFont list and BigFont titles. Some punctuation
and digits are absent from one of those fonts; the error identifies the font and
characters. No accents, emoji, NUL, newline or formatting commands are introduced.
Unchanged original strings retain their bytes even if their existing glyph
choices would be rejected for a new name.

The counters show the ROM font advances in pixels. A BigFont title over the
320-pixel screen width warns about clipping; this is a display warning, not an
arbitrary extra byte limit. Narrower layouts may need shorter names. Blank names
are allowed with a warning. The ghost-data list forces Latin letters to uppercase.
Language availability depends on the running game; stored German/Japanese data
does not add language choices to USA menus. Japanese editing/font replacement
is outside this phase.

## Source and byte protections

All evidence is from the local decomp at
`D:\RomHacking\n64\dkr\research\Diddy-Kong-Racing`:

- `src/game.c:114–124/642–674`: uncompressed asset section25 is indexed by BE
  u32 offsets in section24. The loader allocates the complete indexed byte block,
  then language selection skips0/1/2/3 NUL-terminated strings. Original Rev1 has
  65 records and3,269 indexed bytes in a3,280-byte aligned section.
- `tools/dkr_assets_tool_src/extract/extractTypes/extractLevelName.cpp` confirms
  language order. `text/dkrText.cpp` defines DKRJP's high-bit/two-byte glyph
  encoding. Existing EN/DE/FR records are ASCII; the JP payload and any opaque
  record tail remain byte-identical, as do all unmodified language strings.
- `src/menu.c:12602–12654`: non-JP ghost names copy at most63 bytes into
  `char textBuffer[64]`, then terminate it. The editor refuses longer names
  instead of relying on that screen's truncation.
- `src/font.h:34–57`, `src/font.c:139/438–485/719–758`: section44 starts with
  BE font count4, followed by0x400-byte records. Each has96 eight-byte glyphs
  at+0x100; textureID at+0, advance at+1. Fixed advance and space advance are BE
  u16 at+0x20/+0x24. Missing textureID0xFF is not a printable glyph. Title/banner/
  ghost consumers are in menu.c:8715/9175/9874 and object_functions.c:6673–6695.

The writer rebuilds only name sections24/25, retains record count/level IDs and
table sentinel/padding, preserves original record/section tails, aligns the
physical section and uses the existing bounded master-table/CRC/new-ROM writer.
The report distinguishes indexed bytes allocated in RAM from physical ROM
alignment. More ROM padding does not provide game RAM.

Version12 projects add `course_names`: course ID, original asset SHA-1, protected
encoding tag and bounded full raw record hex. They retain existing artwork/import/
structural data. Names cannot be loaded through legacy fixed byte overlays;
versions1–11 keep their original permissions. No menu/dialogue/textbox assets,
fonts, progression, level counts or save slots become writable.

Automated/native evidence is in STATUS.md. The user checks the exported names
in the game's relevant language and course displays. No review ROM or emulator
run is generated automatically. Dialogue/menu text and autosave remain deferred.
