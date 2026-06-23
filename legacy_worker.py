#!/usr/bin/env python3

import argparse
import json

from legacy_pcbnew_core import export_regions


def main():
    parser = argparse.ArgumentParser(
        description="Legacy pcbnew worker for KiCad 10 compatibility."
    )
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    outputs = export_regions(
        source_pcb=config["source_pcb"],
        output_dir=config["output_dir"],
        regions=config["regions"],
        export_step_files=config.get("export_step_files", True),
        export_format=config.get("export_format"),
        project_dir=config.get("project_dir"),
        export_footprints=config.get("export_footprints", True),
        logger=print,
    )

    print(json.dumps({"outputs": outputs}))


if __name__ == "__main__":
    main()
