import json
import os
import subprocess
import sys
import tempfile

from kipy import KiCad
from kipy.geometry import Vector2
from kipy.util import from_mm


PLUGIN_IDENTIFIER = "com.github.jalinei.multiboard_exporter"
FOOTPRINT_LIBRARY_NAME = "pcb_multiboard"
FOOTPRINT_LIBRARY_DIRNAME = "pcb_multiboard.pretty"
FOOTPRINT_LIBRARY_URI = "${{KIPRJMOD}}/{}".format(FOOTPRINT_LIBRARY_DIRNAME)


def safe_output_name(name):
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)


def sexpr_string(value):
    return '"{}"'.format(str(value).replace("\\", "\\\\").replace('"', '\\"'))


def model_path_reference(model_path, project_dir=None):
    if project_dir:
        relative_path = os.path.relpath(model_path, project_dir)
        return "${{KIPRJMOD}}/{}".format(relative_path.replace(os.sep, "/"))

    return os.path.basename(model_path)


def project_footprint_library_dir(project_dir, output_dir):
    if project_dir:
        return os.path.join(project_dir, FOOTPRINT_LIBRARY_DIRNAME)

    return os.path.join(output_dir, FOOTPRINT_LIBRARY_DIRNAME)


def footprint_library_entry():
    return (
        "  (lib (name {name})(type \"KiCad\")(uri {uri})"
        "(options \"\")(descr \"Multiboard exported footprints\"))"
    ).format(
        name=sexpr_string(FOOTPRINT_LIBRARY_NAME),
        uri=sexpr_string(FOOTPRINT_LIBRARY_URI),
    )


def iter_top_level_lib_ranges(table_text):
    index = 0
    while True:
        start = table_text.find("(lib", index)
        if start == -1:
            return

        if start > 0 and table_text[start - 1] not in " \t\r\n(":
            index = start + 4
            continue

        depth = 0
        in_string = False
        escaped = False
        for pos in range(start, len(table_text)):
            char = table_text[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        yield start, pos + 1
                        index = pos + 1
                        break
        else:
            return


def lib_entry_name_matches(entry, library_name):
    return (
        '(name "{}")'.format(library_name) in entry
        or "(name {})".format(library_name) in entry
    )


def ensure_project_footprint_library(project_dir, logger=None):
    if not project_dir:
        return

    os.makedirs(os.path.join(project_dir, FOOTPRINT_LIBRARY_DIRNAME), exist_ok=True)
    table_path = os.path.join(project_dir, "fp-lib-table")
    entry = footprint_library_entry()

    if os.path.isfile(table_path):
        with open(table_path, "r", encoding="utf-8") as table_file:
            table_text = table_file.read()
    else:
        table_text = "(fp_lib_table\n)\n"

    replacement_range = None
    for start, end in iter_top_level_lib_ranges(table_text):
        if lib_entry_name_matches(table_text[start:end], FOOTPRINT_LIBRARY_NAME):
            replacement_range = (start, end)
            break

    if replacement_range:
        start, end = replacement_range
        updated_text = table_text[:start] + entry + table_text[end:]
    elif table_text.rstrip().endswith(")"):
        insert_at = table_text.rfind(")")
        prefix = table_text[:insert_at].rstrip()
        suffix = table_text[insert_at:]
        updated_text = "{}\n{}\n{}".format(prefix, entry, suffix)
    else:
        updated_text = "(fp_lib_table\n{}\n)\n".format(entry)

    if updated_text != table_text:
        with open(table_path, "w", encoding="utf-8") as table_file:
            table_file.write(updated_text)
        if logger:
            logger("Registered footprint library: {}".format(FOOTPRINT_LIBRARY_URI))


def region_model_offset(region):
    return tuple(region.get("model_offset") or (0.0, 0.0, 0.0))


def region_model_rotation(region):
    return tuple(region.get("model_rotation") or (0.0, 0.0, 0.0))


def write_footprint_file(
    footprint_path,
    footprint_name,
    model_path=None,
    region=None,
    project_dir=None,
):
    model_offset = region_model_offset(region or {})
    model_rotation = region_model_rotation(region or {})
    lines = [
        "(footprint {}".format(sexpr_string(footprint_name)),
        "  (version 20240108)",
        "  (generator \"multiboard_exporter\")",
        "  (layer \"F.Cu\")",
        "  (attr board_only exclude_from_pos_files exclude_from_bom)",
        "  (fp_text reference \"REF**\" (at 0 -2) (layer \"F.SilkS\")",
        "    (effects (font (size 1 1) (thickness 0.1)))",
        "  )",
        "  (fp_text value {} (at 0 2) (layer \"F.Fab\")".format(
            sexpr_string(footprint_name)
        ),
        "    (effects (font (size 1 1) (thickness 0.1)))",
        "  )",
    ]

    if model_path:
        lines.extend(
            [
                "  (model {}".format(
                    sexpr_string(model_path_reference(model_path, project_dir))
                ),
                "    (offset (xyz {} {} {}))".format(*model_offset),
                "    (scale (xyz 1 1 1))",
                "    (rotate (xyz {} {} {}))".format(*model_rotation),
                "  )",
            ]
        )

    lines.append(")")

    with open(footprint_path, "w", encoding="utf-8") as footprint_file:
        footprint_file.write("\n".join(lines))
        footprint_file.write("\n")

    return footprint_path


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


def export_wrl(kicad, kicad_pcb, wrl_out, logger=None):
    try:
        kicad_cli = kicad.get_kicad_binary_path("kicad-cli")
    except Exception:
        kicad_cli = "kicad-cli"

    cmd = [
        kicad_cli,
        "pcb",
        "export",
        "vrml",
        kicad_pcb,
        "-o",
        wrl_out,
        "--force",
        "--units",
        "mm",
    ]

    if logger:
        logger("Running: {}".format(" ".join(cmd)))

    subprocess.run(cmd, check=True)
    return wrl_out


def normalize_export_format(export_step_files=True, export_format=None):
    if export_format is None:
        return "step" if export_step_files else None

    if export_format in ("", "none", "None"):
        return None

    if export_format not in ("step", "wrl"):
        raise ValueError("Unsupported export format: {}".format(export_format))

    return export_format


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


def export_regions(
    kicad,
    source_board,
    output_dir,
    regions,
    export_step_files=True,
    export_format=None,
    project_dir=None,
    export_footprints=True,
    logger=None,
):
    export_format = normalize_export_format(export_step_files, export_format)

    try:
        return export_regions_with_headless_ipc(
            kicad=kicad,
            source_board=source_board,
            output_dir=output_dir,
            regions=regions,
            export_step_files=bool(export_format),
            export_format=export_format,
            project_dir=project_dir,
            export_footprints=export_footprints,
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
        export_step_files=bool(export_format),
        export_format=export_format,
        project_dir=project_dir,
        export_footprints=export_footprints,
        logger=logger,
    )


def export_regions_with_headless_ipc(
    kicad,
    source_board,
    output_dir,
    regions,
    export_step_files=True,
    export_format=None,
    project_dir=None,
    export_footprints=True,
    logger=None,
):
    export_format = normalize_export_format(export_step_files, export_format)
    os.makedirs(output_dir, exist_ok=True)
    footprint_library_dir = None
    if export_footprints:
        footprint_library_dir = project_footprint_library_dir(project_dir, output_dir)
        os.makedirs(footprint_library_dir, exist_ok=True)
        ensure_project_footprint_library(project_dir, logger=logger)
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
        output_wrl = os.path.join(output_dir, "{}.wrl".format(output_base))
        output_footprint = None
        if export_footprints:
            output_footprint = os.path.join(
                footprint_library_dir,
                "{}.kicad_mod".format(output_base),
            )

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
        model_path = None
        if export_format == "step":
            export_step(kicad, output_pcb, output_step, logger=logger)
            result["step"] = output_step
            model_path = output_step
        elif export_format == "wrl":
            export_wrl(kicad, output_pcb, output_wrl, logger=logger)
            result["wrl"] = output_wrl
            model_path = output_wrl

        if export_footprints:
            write_footprint_file(
                output_footprint,
                output_base,
                model_path,
                region,
                project_dir=project_dir,
            )
            result["footprint"] = output_footprint

        outputs.append(result)

    return outputs


def export_regions_with_legacy_worker(
    source_board,
    output_dir,
    regions,
    export_step_files=True,
    export_format=None,
    project_dir=None,
    export_footprints=True,
    logger=None,
):
    export_format = normalize_export_format(export_step_files, export_format)
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
        "export_format": export_format,
        "project_dir": project_dir,
        "export_footprints": export_footprints,
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
            return expected_outputs(
                output_dir,
                regions,
                export_format=export_format,
                project_dir=project_dir,
                export_footprints=export_footprints,
            )

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


def expected_outputs(
    output_dir,
    regions,
    export_step_files=True,
    export_format=None,
    project_dir=None,
    export_footprints=True,
):
    export_format = normalize_export_format(export_step_files, export_format)
    footprint_library_dir = None
    if export_footprints:
        footprint_library_dir = project_footprint_library_dir(project_dir, output_dir)
    outputs = []

    for region in regions:
        name = region["name"]
        output_base = safe_output_name(name)
        result = {
            "name": name,
            "pcb": os.path.join(output_dir, "{}.kicad_pcb".format(output_base)),
        }
        if export_footprints:
            result["footprint"] = os.path.join(
                footprint_library_dir,
                "{}.kicad_mod".format(output_base),
            )
        if export_format == "step":
            result["step"] = os.path.join(output_dir, "{}.step".format(output_base))
        elif export_format == "wrl":
            result["wrl"] = os.path.join(output_dir, "{}.wrl".format(output_base))
        outputs.append(result)

    return outputs
