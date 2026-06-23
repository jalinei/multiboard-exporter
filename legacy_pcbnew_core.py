import os
import subprocess

import pcbnew


FOOTPRINT_LIBRARY_NAME = "pcb_multiboard"
FOOTPRINT_LIBRARY_DIRNAME = "pcb_multiboard.pretty"
FOOTPRINT_LIBRARY_URI = "${{KIPRJMOD}}/{}".format(FOOTPRINT_LIBRARY_DIRNAME)


def from_mm(value):
    return pcbnew.FromMM(float(value))


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


def make_vec2i(x_iu, y_iu):
    if hasattr(pcbnew, "VECTOR2I"):
        return pcbnew.VECTOR2I(x_iu, y_iu)

    return pcbnew.wxPoint(x_iu, y_iu)


def vec_x(vec):
    return vec.x


def vec_y(vec):
    return vec.y


def load_board_or_die(source_pcb):
    source_pcb = os.path.abspath(source_pcb)

    if not os.path.isfile(source_pcb):
        raise FileNotFoundError("PCB file does not exist: {}".format(source_pcb))

    board = pcbnew.LoadBoard(source_pcb)

    if board is None:
        raise RuntimeError("pcbnew.LoadBoard() returned None for {}".format(source_pcb))

    return board


def get_grid_origin_iu(board):
    if hasattr(board, "GetGridOrigin"):
        return board.GetGridOrigin()

    ds = board.GetDesignSettings()
    if hasattr(ds, "GetGridOrigin"):
        return ds.GetGridOrigin()

    raise RuntimeError("This pcbnew API does not expose GetGridOrigin().")


def set_grid_origin_iu(board, origin_iu):
    if hasattr(board, "SetGridOrigin"):
        board.SetGridOrigin(origin_iu)
        return

    ds = board.GetDesignSettings()
    if hasattr(ds, "SetGridOrigin"):
        ds.SetGridOrigin(origin_iu)
        return

    raise RuntimeError("This pcbnew API does not expose SetGridOrigin().")


def user_point_to_absolute_iu(source_grid_origin_iu, x_user_mm, y_user_mm):
    return make_vec2i(
        vec_x(source_grid_origin_iu) + from_mm(x_user_mm),
        vec_y(source_grid_origin_iu) + from_mm(y_user_mm),
    )


def user_bbox_to_absolute_bbox_iu(source_grid_origin_iu, bbox_user_mm):
    xmin_u, ymin_u, xmax_u, ymax_u = bbox_user_mm
    p1 = user_point_to_absolute_iu(source_grid_origin_iu, xmin_u, ymin_u)
    p2 = user_point_to_absolute_iu(source_grid_origin_iu, xmax_u, ymax_u)

    return (
        min(vec_x(p1), vec_x(p2)),
        min(vec_y(p1), vec_y(p2)),
        max(vec_x(p1), vec_x(p2)),
        max(vec_y(p1), vec_y(p2)),
    )


def point_in_region_iu(x_iu, y_iu, region_iu):
    xmin, ymin, xmax, ymax = region_iu
    return xmin <= x_iu <= xmax and ymin <= y_iu <= ymax


def bbox_overlaps_region_iu(bbox, region_iu):
    xmin, ymin, xmax, ymax = region_iu
    return not (
        bbox.GetRight() < xmin
        or bbox.GetX() > xmax
        or bbox.GetBottom() < ymin
        or bbox.GetY() > ymax
    )


def footprint_in_region(fp, region_iu):
    pos = fp.GetPosition()
    return point_in_region_iu(vec_x(pos), vec_y(pos), region_iu)


def board_item_in_region(item, region_iu):
    if hasattr(item, "GetBoundingBox"):
        return bbox_overlaps_region_iu(item.GetBoundingBox(), region_iu)

    return True


def remove_item(board, item):
    for method_name in ("RemoveNative", "Remove", "Delete"):
        method = getattr(board, method_name, None)
        if method is not None:
            method(item)
            return

    raise RuntimeError("Could not remove item {}; no known remove method.".format(item))


def get_zones(board):
    if hasattr(board, "Zones"):
        return list(board.Zones())

    if hasattr(board, "GetAreaCount") and hasattr(board, "GetArea"):
        return [board.GetArea(i) for i in range(board.GetAreaCount())]

    return []


def collect_items_to_remove(board, region_iu):
    to_remove = []

    for fp in list(board.GetFootprints()):
        if not footprint_in_region(fp, region_iu):
            to_remove.append(fp)

    for trk in list(board.GetTracks()):
        if not board_item_in_region(trk, region_iu):
            to_remove.append(trk)

    for drawing in list(board.Drawings()):
        if not board_item_in_region(drawing, region_iu):
            to_remove.append(drawing)

    for zone in get_zones(board):
        if not board_item_in_region(zone, region_iu):
            to_remove.append(zone)

    return to_remove


def generate_temp_board(source_pcb, output_pcb, region_name, cfg, logger=None):
    board = load_board_or_die(source_pcb)
    source_grid_origin_iu = get_grid_origin_iu(board)
    region_iu = user_bbox_to_absolute_bbox_iu(source_grid_origin_iu, cfg["bbox"])
    new_origin_iu = user_point_to_absolute_iu(
        source_grid_origin_iu,
        cfg["new_origin"][0],
        cfg["new_origin"][1],
    )

    to_remove = collect_items_to_remove(board, region_iu)
    if logger:
        logger("[{}] removing {} item(s)".format(region_name, len(to_remove)))

    for item in to_remove:
        remove_item(board, item)

    set_grid_origin_iu(board, new_origin_iu)
    os.makedirs(os.path.dirname(os.path.abspath(output_pcb)), exist_ok=True)
    pcbnew.SaveBoard(output_pcb, board)

    if logger:
        logger("[{}] wrote {}".format(region_name, output_pcb))

    return output_pcb


def export_step(kicad_pcb, step_out, logger=None):
    cmd = [
        "kicad-cli",
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


def export_wrl(kicad_pcb, wrl_out, logger=None):
    cmd = [
        "kicad-cli",
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


def export_regions(
    source_pcb,
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
    outputs = []

    for region in regions:
        name = region["name"]
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
        temp_pcb = os.path.join(output_dir, "{}.kicad_pcb".format(safe_name))
        temp_step = os.path.join(output_dir, "{}.step".format(safe_name))
        temp_wrl = os.path.join(output_dir, "{}.wrl".format(safe_name))
        temp_footprint = None
        if export_footprints:
            temp_footprint = os.path.join(
                footprint_library_dir,
                "{}.kicad_mod".format(safe_name),
            )

        generate_temp_board(
            source_pcb,
            temp_pcb,
            name,
            {"bbox": region["bbox"], "new_origin": region["new_origin"]},
            logger=logger,
        )

        result = {"name": name, "pcb": temp_pcb}
        model_path = None
        if export_format == "step":
            export_step(temp_pcb, temp_step, logger=logger)
            result["step"] = temp_step
            model_path = temp_step
        elif export_format == "wrl":
            export_wrl(temp_pcb, temp_wrl, logger=logger)
            result["wrl"] = temp_wrl
            model_path = temp_wrl

        if export_footprints:
            write_footprint_file(
                temp_footprint,
                safe_name,
                model_path,
                region,
                project_dir=project_dir,
            )
            result["footprint"] = temp_footprint

        outputs.append(result)

    return outputs
