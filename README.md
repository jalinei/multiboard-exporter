# Multi-board Geometry Exporter

This is a KiCad PCB editor IPC action plugin extracted from `split_boards.py`.

It lets the user define one or more board bounding boxes in millimeters relative
to the source board grid origin. For each board, it creates a temporary
`.kicad_pcb` containing only the items inside that board region, sets that temp
board's grid origin, writes a matching `.kicad_mod` footprint into
`${KIPRJMOD}/pcb_multiboard.pretty`, and can export STEP or WRL geometry with
`kicad-cli`.

## KiCad API

The plugin entry point uses KiCad's IPC plugin system and `kicad-python`, not
the legacy SWIG `pcbnew.ActionPlugin` API.

It has two export backends:

- KiCad 11 and newer: pure IPC. The plugin reads the open board through IPC,
  then uses KiCad's headless IPC mode to create and mutate temporary per-board
  copies without touching the currently open board.
- KiCad 10: IPC GUI/action plus a legacy worker subprocess. KiCad 10 IPC does
  not support headless document loading, so the worker uses the deprecated
  `pcbnew` module only for temporary board-file generation. This keeps the
  installable action on the modern IPC plugin system while preserving KiCad 10
  compatibility.

For KiCad 10, the legacy worker must be run by a Python interpreter that can
`import pcbnew`. On Linux this is often the system `python3`. If KiCad's IPC
plugin environment cannot find such an interpreter automatically, set
`KICAD_LEGACY_PYTHON` before launching KiCad.

## Install

Make sure the KiCad plugin API is enabled in KiCad preferences before
installing or refreshing the plugin.

Copy this whole plugin directory, including `plugin.json`, `requirements.txt`,
`refresh_stackup_light_24.png`, `refresh_stackup_dark_24.png`,
`legacy_worker.py`, `legacy_pcbnew_core.py`, and `multiboard_exporter/`, into
KiCad's IPC plugin directory, then restart KiCad or refresh plugins from the PCB
editor.

The default Linux path is:

- `~/.local/share/KiCad/<version>/plugins/com_github_jalinei_multiboard_exporter/`

KiCad 10 requires the `plugin.json` identifier to be reverse-DNS style. This
plugin uses `com.github.jalinei.multiboard_exporter`.

KiCad creates a Python environment for the plugin and installs
`requirements.txt`. The action appears in the PCB editor toolbar/preferences as
`Export Board Geometries`.

## Region Coordinates

Each row in the GUI defines:

- `Name`: output basename.
- `X min`, `Y min`, `X max`, `Y max`: selection box relative to the current
  board grid origin, in mm.
- `Origin X`, `Origin Y`: new grid origin for the generated temp board, also
  relative to the source grid origin.
- `3D X`, `3D Y`, `3D Z`: model offset written into the generated footprint's
  3D model entry, in mm.
- `Rot X`, `Rot Y`, `Rot Z`: model rotation written into the generated
  footprint's 3D model entry, in degrees.

KiCad PCB coordinates use positive X to the right and positive Y downward, so a
board above a bottom-left origin usually has negative Y coordinates.

The `Apply` button saves the current output directory, geometry format, and
board rows without exporting. `Export` saves those same settings before
generating files.

The geometry format selector can export STEP, export WRL through
`kicad-cli pcb export vrml`, or skip geometry export. Each board always gets a
per-board `.kicad_pcb`. The footprint library checkbox is enabled by default;
when enabled, footprints are written to `${KIPRJMOD}/pcb_multiboard.pretty`,
and the project `fp-lib-table` is updated with that library. The footprint
includes a 3D model reference when STEP or WRL export is enabled. Generated 3D
model paths use `${KIPRJMOD}` and are relative to the source project directory.

## CLI

The original proof-of-concept entry point still works. It uses the same legacy
worker code as the KiCad 10 fallback:

```sh
python3 split_boards.py path/to/source.kicad_pcb --export-step
```
