import json
import os
import subprocess
import sys
import tempfile

from kipy import KiCad
from kipy.geometry import Vector2
from kipy.util import from_mm


PLUGIN_IDENTIFIER = "com.github.jal.multiboard_geometry_exporter"


def safe_output_name(name):
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)


def point_in_region(point, region):
    xmin, ymin, xmax, ymax = region
    return xmin <= point.x <= xmax and ymin <= point.y <= ymax


def bbox_overlaps_region(bbox, region):
    xmin, ymin, xmax, ymax = region
    left, top, right, bottom = box_edges(bbox)
    return not (right < xmin or left > xmax or bottom < ymin or top > ymax)


def box_edges(bbox):
    candidates = (
        ("left", "top", "right", "bottom"),
        ("x", "y", "right", "bottom"),
        ("min_x", "min_y", "max_x", "max_y"),
        ("xmin", "ymin", "xmax", "ymax"),
    )

    for names in candidates:
        if all(hasattr(bbox, name) for name in names):
            return tuple(getattr(bbox, name) for name in names)

    if hasattr(bbox, "pos") and hasattr(bbox, "size"):
        return (
            bbox.pos.x,
            bbox.pos.y,
            bbox.pos.x + bbox.size.x,
            bbox.pos.y + bbox.size.y,
        )

    raise RuntimeError("Unsupported Box2 shape returned by kicad-python: {}".format(type(bbox)))


def user_point_to_absolute(source_grid_origin, x_user_mm, y_user_mm):
    return Vector2.from_xy(
        source_grid_origin.x + from_mm(float(x_user_mm)),
        source_grid_origin.y + from_mm(float(y_user_mm)),
    )


def user_bbox_to_absolute(source_grid_origin, bbox_user_mm):
    xmin_u, ymin_u, xmax_u, ymax_u = bbox_user_mm
    p1 = user_point_to_absolute(source_grid_origin, xmin_u, ymin_u)
    p2 = user_point_to_absolute(source_grid_origin, xmax_u, ymax_u)

    return (
        min(p1.x, p2.x),
        min(p1.y, p2.y),
        max(p1.x, p2.x),
        max(p1.y, p2.y),
    )


def resolve_grid_origin_type():
    modules = (
        "kipy.board_types",
        "kipy.proto.board.board_types",
        "kipy.proto.board.types",
        "kipy.proto.board.board",
    )
    enum_names = (
        "BoardOriginType",
        "BoardOrigin",
        "OriginType",
    )
    value_names = (
        "BOT_GRID_ORIGIN",
        "BOARD_ORIGIN_GRID",
        "GRID_ORIGIN",
        "ORIGIN_GRID",
    )

    for module_name in modules:
        try:
            module = __import__(module_name, fromlist=["_"])
        except ImportError:
            continue

        for enum_name in enum_names:
            enum = getattr(module, enum_name, None)
            if enum is None:
                continue
            for value_name in value_names:
                value = getattr(enum, value_name, None)
                if value is not None:
                    return value

        for value_name in value_names:
            value = getattr(module, value_name, None)
            if value is not None:
                return value

    # kicad-python's protobuf enums are ints at the API boundary. Keep this
    # fallback isolated so it is easy to adjust if KiCad renames the exported
    # enum but keeps the wire value stable.
    return 1


GRID_ORIGIN_TYPE = resolve_grid_origin_type()


def get_grid_origin(board):
    return board.get_origin(GRID_ORIGIN_TYPE)


def set_grid_origin(board, origin):
    board.set_origin(GRID_ORIGIN_TYPE, origin)


def export_step(kicad, kicad_pcb, step_out, logger=None):
    try:
        kicad_cli = kicad.get_kicad_binary_path("kicad-cli")
    except Exception:
        kicad_cli = "kicad-cli"

    cmd = [
        kicad_cli,
        "pcb",
        "export",
        "step",
        kicad_pcb,
        "-o",
        step_out,
        "--force",
        "--grid-origin",
        "--subst-models",
        "--include-tracks",
        "--include-pads",
        "--include-zones",
        "--include-inner-copper",
        "--include-silkscreen",
        "--include-soldermask",
    ]

    if logger:
        logger("Running: {}".format(" ".join(cmd)))

    subprocess.run(cmd, check=True)
    return step_out


def collect_items_to_remove(board, region):
    to_remove = []

    for footprint in list(board.get_footprints()):
        if not point_in_region(footprint.position, region):
            to_remove.append(footprint)

    for item in list(board.get_tracks()) + list(board.get_vias()):
        if not item_overlaps_region(board, item, region):
            to_remove.append(item)

    for item in list(board.get_shapes()) + list(board.get_text()):
        if not item_overlaps_region(board, item, region):
            to_remove.append(item)

    for zone in list(board.get_zones()):
        if not item_overlaps_region(board, zone, region):
            to_remove.append(zone)

    return to_remove


def item_overlaps_region(board, item, region):
    try:
        bbox = board.get_item_bounding_box(item, include_text=True)
    except Exception:
        bbox = None

    if bbox is not None:
        return bbox_overlaps_region(bbox, region)

    position = getattr(item, "position", None)
    if position is not None:
        return point_in_region(position, region)

    return True


def export_regions(kicad, source_board, output_dir, regions, export_step_files=True, logger=None):
    try:
        return export_regions_with_headless_ipc(
            kicad=kicad,
            source_board=source_board,
            output_dir=output_dir,
            regions=regions,
            export_step_files=export_step_files,
            logger=logger,
        )
    except Exception as exc:
        if logger:
            logger(
                "Headless IPC backend failed; trying KiCad 10 legacy pcbnew worker: "
                "{}".format(exc)
            )

    return export_regions_with_legacy_worker(
        source_board=source_board,
        output_dir=output_dir,
        regions=regions,
        export_step_files=export_step_files,
        logger=logger,
    )


def export_regions_with_headless_ipc(
    kicad,
    source_board,
    output_dir,
    regions,
    export_step_files=True,
    logger=None,
):
    os.makedirs(output_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="kicad_multiboard_")
    source_temp = os.path.join(tmp_dir, "source.kicad_pcb")

    with open(source_temp, "w", encoding="utf-8") as source_file:
        source_file.write(source_board.get_as_string())

    source_origin = get_grid_origin(source_board)
    outputs = []

    try:
        kicad_cli = kicad.get_kicad_binary_path("kicad-cli")
    except Exception:
        kicad_cli = None

    for region in regions:
        name = region["name"]
        output_base = safe_output_name(name)
        output_pcb = os.path.join(output_dir, "{}.kicad_pcb".format(output_base))
        output_step = os.path.join(output_dir, "{}.step".format(output_base))

        worker = KiCad(headless=True, kicad_cli_path=kicad_cli, file_path=source_temp)
        try:
            work_board = worker.get_board()
            if work_board is None:
                raise RuntimeError("Headless KiCad did not open {}".format(source_temp))

            work_board.save_as(output_pcb, overwrite=True, include_project=False)
            absolute_region = user_bbox_to_absolute(source_origin, region["bbox"])
            new_origin = user_point_to_absolute(
                source_origin,
                region["new_origin"][0],
                region["new_origin"][1],
            )

            to_remove = collect_items_to_remove(work_board, absolute_region)
            if logger:
                logger("[{}] removing {} item(s)".format(name, len(to_remove)))

            if to_remove:
                work_board.remove_items(to_remove)

            set_grid_origin(work_board, new_origin)
            work_board.save()
        finally:
            worker.close()

        result = {"name": name, "pcb": output_pcb}
        if export_step_files:
            export_step(kicad, output_pcb, output_step, logger=logger)
            result["step"] = output_step

        outputs.append(result)

    return outputs


def export_regions_with_legacy_worker(
    source_board,
    output_dir,
    regions,
    export_step_files=True,
    logger=None,
):
    os.makedirs(output_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="kicad_multiboard_")
    source_temp = os.path.join(tmp_dir, "source.kicad_pcb")
    config_path = os.path.join(tmp_dir, "legacy_worker_config.json")

    with open(source_temp, "w", encoding="utf-8") as source_file:
        source_file.write(source_board.get_as_string())

    config = {
        "source_pcb": source_temp,
        "output_dir": output_dir,
        "regions": regions,
        "export_step_files": export_step_files,
    }

    with open(config_path, "w", encoding="utf-8") as config_file:
        json.dump(config, config_file)

    worker = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "legacy_worker.py",
    )

    failures = []
    for python in legacy_python_candidates():
        cmd = [python, worker, "--config", config_path]
        if logger:
            logger("Running legacy worker: {}".format(" ".join(cmd)))

        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )

        if completed.returncode == 0:
            if logger and completed.stdout.strip():
                for line in completed.stdout.strip().splitlines():
                    logger(line)
            return expected_outputs(output_dir, regions, export_step_files)

        failures.append(
            "{} exited with {}\nstdout:\n{}\nstderr:\n{}".format(
                python,
                completed.returncode,
                completed.stdout,
                completed.stderr,
            )
        )

    raise RuntimeError(
        "Could not run the KiCad 10 legacy pcbnew worker. "
        "Set KICAD_LEGACY_PYTHON to a Python interpreter that can import pcbnew.\n\n"
        + "\n\n".join(failures)
    )


def legacy_python_candidates():
    candidates = [
        os.environ.get("KICAD_LEGACY_PYTHON"),
        "python3",
        "python",
        sys.executable,
    ]
    seen = set()
    result = []

    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)

    return result


def expected_outputs(output_dir, regions, export_step_files):
    outputs = []

    for region in regions:
        name = region["name"]
        output_base = safe_output_name(name)
        result = {
            "name": name,
            "pcb": os.path.join(output_dir, "{}.kicad_pcb".format(output_base)),
        }
        if export_step_files:
            result["step"] = os.path.join(output_dir, "{}.step".format(output_base))
        outputs.append(result)

    return outputs
