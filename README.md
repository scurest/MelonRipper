<p align=center>
  <img src="imgs/frontispiece.png"
    title="Game is The Wizard of Oz: Beyond the Yellow Brick Road">
</p>
<h2 align=center>MelonRipper</h2>

This repo has some stuff for ripping 3D models from the Nintendo DS.
It works Ninja Ripper-style,
where to rip a model, you play in an emulator
until the model is on screen,
then press a key to dump everything drawn in one frame to a file.
A Blender addon can import the dump.

If you want to convert an .nsbmd model file instead,
I have [another project](https://github.com/scurest/apicula)
for that.

## How it works

MelonRipper consists of two parts:
a patched melonDS for ripping dump files,
and a Blender addon for importing them.

### melonDS

First, you need to build the patched melonDS.
Windows users can download a
[precompiled EXE](https://github.com/scurest/melonDS/releases/tag/MelonRipperBuild).
Otherwise, compile the
[scurest:MelonRipper branch](https://github.com/scurest/melonDS/tree/MelonRipper)
from my copy of melonDS.
Build instructions are in melonDS's ReadMe.

Open the emulator.
There should be a new hotkey for ripping a frame.
Go to _Config ‣ Input and hotkeys ‣ Add-ons_
and assign a hotkey to "[MelonRipper] Rip"
(I used [F]).

<img src="imgs/melonDSHotkeys.png">

Now when you're playing a game
you can press the hotkey
to rip the next frame to a `.dump` file
in the current directory.

### Blender

Blender 2.82 or later is required.

To install the addon, open
[`import_melon_rip.py`](https://raw.githubusercontent.com/scurest/MelonRipper/master/import_melon_rip.py)
and save it to your computer.
Then in Blender,
go to _Edit ‣ Preferences ‣ Add-ons ‣ Install..._
and select the file you just saved.
Enable the addon by clicking the checkbox
next to "Import: MelonRipper NDS Dumps" in the addon list
(use the search box to find it).
See the
[Blender Manual](https://docs.blender.org/manual/en/latest/editors/preferences/addons.html#rd-party-add-ons)
or
[this question](https://blender.stackexchange.com/questions/1688/installing-an-addon/1689)
for more help installing addons.

Then go to _File ‣ Import ‣ MelonRipper NDS Dump_
and pick the `.dump` file you ripped with melonDS
to import it.


## Tips & Tricks

* If the colors are washed out,
  try switching Blender's color space from "Filmic" to "Standard".
  See [this answer](https://blender.stackexchange.com/questions/164677/images-as-emitters-constantly-come-out-dull-white-emission-not-actually-white).

* If you're having trouble finding the model in the viewport,
  try _View ‣ Frame Selected_.

* Sometimes different parts of the scene are
  displaced relative to each other.
  I think that's because they're drawn with different "cameras".
  (Dumped vertex position are all after the ModelView matrix
  but before the Projection.)

* Normals aren't ripped.
  The calculated lighting is baked into the vertex colors.

* Strip connectivity is not preserved.
  All faces in Blender are totally separate from each other,
  even if they were originally part of a polygon strip.

* Vertex colors in the middle of a quad
  will look different in Blender than on the DS
  because quads on a PC are rendered as two tris,
  while the DS renders quads as real quads.
  The [melonDS blog](http://melonds.kuribo64.net/comments.php?id=122)
  has a great explanation for this.

* Translucent (partially transparent) faces are imported with "Alpha Blend".
  This may have sorting problems in the Eevee renderer.
  If you have sorting issues, try Cycles.

* Some DS effects aren't implemented:
  fog, highlight, shadow, wireframe, edgemarking, depth equal, rear plane.

* Exporting to .gltf sort of works (use Blender ≥2.92 for best results).
  You will probably need to modify the materials to export to other formats.
