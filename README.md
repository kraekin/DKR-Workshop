# DKR Workshop

**Version 0.26.0 · Public beta · Python script release**

DKR Workshop is a desktop level, track and asset editor for **Diddy Kong Racing
on Nintendo 64**. Explore the original courses, rearrange objects, create custom
tracks in Blender, replace textures, and export your changes to a separate ROM.

This package runs directly from Python. It includes the application source,
launcher, dependency list and application icon. You supply your own legally obtained ROM.

## Requirements

- **Windows, with 64-bit Python 3.11 or newer.** The included launcher is for Windows.
- **OpenGL 3.3-capable graphics hardware and a working desktop graphics driver.**
- An original **Diddy Kong Racing USA Rev 1 / USA 1.1** ROM.
- An emulator or compatible hardware to play your exported ROMs.

The editor accepts `.z64`, `.v64` and `.n64` byte orders and converts them in
memory.

For reference, the supported original ROM's SHA-1 after byte-order normalization is:

```text
6d96743d46f8c0cd0edb0ec5600b003c89b93755
```

## Screenshots

| **Main Windowr** | **Editing a Trackr** |
| :---: | :---: |
| <img width="450" alt="Main Window" src="https://github.com/user-attachments/assets/7fdb5977-9173-4058-beba-ee463e78584e" /> | <img width="450" alt="python_CdKQm3xFLQ" src="https://github.com/user-attachments/assets/8a7f9015-c64a-40b5-b977-63749135e75c" /> |
| Main window showing the starting hub | Editing Ancient Lake |
| **Materials and Textures** | **Object Models and Animation** |
| <img width="450" alt="python_hWjsykT2zW" src="https://github.com/user-attachments/assets/41f6cd9c-ea47-436e-805b-b4e2a4c6002c" /> | <img width="450" alt="python_RHeS5TLKAR" src="https://github.com/user-attachments/assets/adf3ba94-c2b9-4696-aac7-8c5613ae8b5f" /> |
| Change track materials and driving surfaces, or replace textures with your own artwork. | Preview animations and export models for editing in Blender. |

## Installation and launch

1. Extract the whole release folder somewhere you can write files. Keep
   `src`, `requirements.txt` and `DKR Workshop.cmd` together.
2. Open PowerShell in that folder and run:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Double-click **DKR Workshop.cmd** to launch the editor.

You only need to install the dependencies once for that environment. The launcher
uses the `.venv` folder automatically, so activating it is unnecessary.

You can also launch it from PowerShell:

```powershell
.\.venv\Scripts\python.exe -B -m src.main
```

If you downloaded the separate **one-file executable edition**, run
`DKR Workshop.exe` instead; that edition includes its Python runtime.

## Your first edit

1. Choose **File → Open ROM…** and select your original USA Rev 1 ROM.
2. Select a course or hub from the level list on the left.
3. Click an object in the viewport or its row in **Objects**. Double-click a row
   to focus the camera on it.
4. Move it using the colored handles, or edit its coordinates in the inspector.
   Double-click a property value to edit that field.
5. Choose **File → Save Project** to save your editable `.dkrproj`.
6. Choose **File → Save As Edited ROM…** to export a separate `.z64` for playing.

Use **Undo** (`Ctrl+Z`) and **Redo** (`Ctrl+Y` or `Ctrl+Shift+Z`) to reverse edits.

## Projects and ROM exports

| File or action | Purpose |
| --- | --- |
| Original ROM | The unchanged base used to load game data and reopen projects. Keep it. |
| `.dkrproj` project | Stores your edits and their original-ROM identity so you can resume work. |
| Save As Edited ROM… | Builds a separate playable ROM containing the applied edits. |
| ROM Budget and Project Changes… | Shows changed assets, known shared uses and available ROM storage. |

**Save both your project and your exported ROM.** Exporting a ROM does not save
the project. Opening an exported ROM does not recover its project history.

To continue later, use **File → Open Project…**. If the original ROM has moved,
open it first, then reopen the project. ROM export refuses to overwrite the
loaded original ROM's path.

In editors with a preview or draft, use **Apply** to commit the changes to the
project before saving or exporting. Closing a draft without applying discards it.

## Camera controls

| Control | Action |
| --- | --- |
| Right mouse button + drag | Look around |
| Middle mouse button + drag | Pan |
| Alt + right mouse button + drag | Orbit around the view target |
| W / S | Move forward / backward while the camera is captured |
| A / D | Strafe left / right while the camera is captured |
| Q / E | Move down / up while the camera is captured |
| Shift | Boost movement speed |
| Mouse wheel | Zoom |
| F | Fit the course or isolated segment |
| Escape | Cancel the active gesture or release camera capture |
| Double-click an object row | Focus that object |

Use the camera toolbar to switch between **Perspective**, **Top**, **Front** and
**Right** views. **Help → Camera Controls** also lists the controls.

The **Grid** arrow menu controls automatic visibility and the working plane.
The corner **Axes** indicator shows world orientation: X is red, Y green and Z blue.

## What you can edit

| Tool | Where to find it | Main uses |
| --- | --- | --- |
| Placed objects | Objects tab | Move objects, edit parameters, add, duplicate and delete entries. |
| Track geometry | Geometry → Mesh | Reshape existing geometry or import a replacement OBJ track. |
| Track materials | Geometry → Materials | Change batch materials, driving surfaces, UVs and vertex colors. |
| Level settings | Settings tab | Adjust supported level defaults, references, vehicles, laps and fog. |
| Placement helpers | Tools → Placement | Group transforms, alignment, snapping and surface placement. |
| Routes | Tools → Routes | Edit checkpoint AI lanes and directed AI-node connections. |
| Minimap | Tools → Minimap | Adjust the map sprite, positioning, tint and marker alignment. |
| Cinematics | Tools → Cinematics | Edit supported actor/camera paths, timing and events. |
| Course Builder | Edit → Course Builder… | Clear selected object categories, create checkpoint routes and place a start grid. |
| Course names | Edit → Course Names… | Edit the existing English, German and French course names. |
| Textures and sprites | Edit → Texture & Sprite Browser / PNG… | Export PNGs, import replacements, adjust supported anchors and timing. |
| Shared object properties | Edit → Global Object Properties… | Edit supported shared object definitions and artwork references. |
| Object models and animation | Edit → Object Models & Animation… | Export/import meshes and clips, edit model data and preview changes. |

### Changing a track texture

Open **Geometry → Materials**, click the track surface to select its batch, then
choose **Change this batch’s material…**. Select a material in the thumbnail
picker and apply it. A batch can contain several faces, so the assignment affects
the whole batch.

**Edit shared material…** changes the material used by every batch referencing
that course material. **Edit texture image…** opens the PNG workflow. Shared
texture pixels and object assets can affect more than one course; review the
listed uses in the relevant editor.

### Making a custom track in Blender

1. Export a size reference with **File → Export Wavefront .OBJ…**. Keep its OBJ,
   MTL and texture files together.
2. Import it into Blender at **Scale 1**, **Forward −Z**, **Up Y**. Build your new
   track in a separate collection and export only the meshes you want to use.
3. Export Wavefront OBJ at **Scale 1**, **Forward −Z**, **Up Y**, with UVs,
   triangulation, materials and applied modifiers enabled. Save texture images
   as PNGs and keep them with the MTL/OBJ.
4. Select the target course in Workshop and use **Geometry → Import OBJ…**.
   Review the preview, material mapping and resource report, then apply.
5. Use **Course Builder** to clear unwanted placed objects and build or align the
   checkpoint route and start grid. Save the project, export a ROM and play it.

The OBJ exchange scale is **1 OBJ unit = 100 game units**. Fresh Workshop exports
are scaled down by `0.01`; track import defaults to a `100` multiplier. Leave
Blender's import/export scales at `1`. Object-model OBJ import restores the scale
automatically. Coordinates displayed inside Workshop remain in game units.

Track replacement and placed objects are separate: importing geometry does not
automatically relocate the existing checkpoints, starts or scenery. Driving
surfaces are material properties, separate from the texture image.

Static object-model imports support added or extruded faces. Animated models
retain their existing topology and animation groups.

## Preview and beta notes

Sprites, models, special artwork and logic markers have separate visibility
controls. Animation playback, sky, fog, texture motion and water controls help
preview supported artwork.

Available ROM space is **storage**, not extra runtime RAM. A change fitting in
the ROM does not guarantee that an arbitrarily large course or object population
fits the game's memory limits. The importer and export report provide checks
and explanations when a limit is exceeded.

Some parameters are still unknown. They retain their byte offsets rather than a description. 
Keep project backups while exploring unfamiliar fields.


## Credits and acknowledgements

### Diddy Kong Racing decompilation

Special thanks to **DavidSM64 and all contributors to the
[Diddy Kong Racing decompilation project](https://github.com/DavidSM64/Diddy-Kong-Racing)**.

Their work provided the authoritative reference for the game's binary layouts,
asset tables, compression, rendering structures, object parameters and runtime
behavior used to develop DKR Workshop. The project's tools and documentation
were also essential references for understanding how the original game loads
and uses its data.

### Libraries and tools

DKR Workshop uses **Python**, **PySide6 / Qt**, **PyOpenGL**, **NumPy**, **Pillow**
and **Zstandard**. The separate executable edition is packaged with **Nuitka**.
Thanks to the maintainers and contributors of these projects.

### Original game

**Diddy Kong Racing** was developed by **Rare** and published by **Nintendo**.
Game characters, artwork, names and other game assets belong to their respective
owners. The application icon uses Taj and lettering from the original game.

DKR Workshop is an unofficial fan project and is not affiliated with or endorsed
by Rare or Nintendo. No game ROM is included.
