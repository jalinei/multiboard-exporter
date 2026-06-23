#!/usr/bin/env python3

import argparse
import os
import sys

from legacy_pcbnew_core import export_regions


# Selection boxes are expressed in mm relative to the SOURCE board grid origin.
#
# This matches the coordinate system shown in KiCad when coordinates are
# displayed relative to the user/grid origin.
#
# Important:
#   KiCad PCB coordinates use X to the right and Y downward.
#   So if the origin is at the bottom-left of a board, points above it have
#   negative Y values.
#
# For your toy file:
#
#   Source grid origin:
#       absolute KiCad coordinate = 53.25, 144.025 mm
#
#   Board_A:
#       outline absolute = x 53.25..93.25, y 94.025..144.025
#       relative to source origin = x 0..40, y -50..0
#
#   Board_B:
#       outline absolute = x 100.25..120.25, y 119.025..144.025
#       relative to source origin = x 47..67, y -25..0
#
# A 0.5 mm margin is added to each selection box.
BOARD_REGIONS_USER_MM = {
    "Board_A": {
        "bbox": (-0.5, -50.5, 40.5, 0.5),

        # New origin for the generated Board_A temp file.
        # Relative to the source grid origin.
        # This is Board_A bottom-left.
        "new_origin": (0.0, 0.0),
    },
    "Board_B": {
        "bbox": (46.5, -25.5, 67.5, 0.5),

        # New origin for the generated Board_B temp file.
        # Relative to the source grid origin.
        # This is Board_B bottom-left.
        "new_origin": (47.0, 0.0),
    },
}


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Split a multi-board KiCad PCB into temporary per-board PCB files "
            "using selection boxes relative to the source board grid origin."
        )
    )

    parser.add_argument(
        "source",
        help="Source multi-board .kicad_pcb",
    )

    parser.add_argument(
        "-o",
        "--out-dir",
        default="build_stack",
        help="Output directory for temporary .kicad_pcb and .step files",
    )

    parser.add_argument(
        "--export-step",
        action="store_true",
        help="Also export STEP files using kicad-cli",
    )

    args = parser.parse_args()

    source_pcb = os.path.abspath(args.source)

    if not os.path.isfile(source_pcb):
        print(f"Input file not found: {source_pcb}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)

    regions = [
        {
            "name": region_name,
            "bbox": cfg["bbox"],
            "new_origin": cfg["new_origin"],
        }
        for region_name, cfg in BOARD_REGIONS_USER_MM.items()
    ]

    export_regions(
        source_pcb=source_pcb,
        output_dir=args.out_dir,
        regions=regions,
        export_step_files=args.export_step,
        logger=print,
    )

    print("\nDone.")


if __name__ == "__main__":
    main()
