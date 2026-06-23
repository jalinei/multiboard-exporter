import hashlib
import os
import sys
import traceback

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

import wx
from kipy import KiCad

from multiboard_exporter.dialog import MultiBoardExporterDialog
from multiboard_exporter.ipc_core import export_regions


def settings_path_for_board(project_path, board_name):
    config_dir = wx.StandardPaths.Get().GetUserConfigDir()
    plugin_dir = os.path.join(config_dir, "multiboard_exporter")
    project_key = hashlib.sha256(os.path.abspath(project_path).encode("utf-8")).hexdigest()[:16]
    board_key = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in board_name or "board")
    return os.path.join(plugin_dir, "{}__{}.json".format(project_key, board_key))


def show_error(title, exc):
    wx.MessageBox(
        "{}\n\n{}".format(exc, traceback.format_exc()),
        title,
        wx.OK | wx.ICON_ERROR,
    )


def main():
    title = "Multi-board Geometry Exporter"
    app = wx.App(False)

    try:
        kicad = KiCad()
        board = kicad.get_board()
        if board is None:
            wx.MessageBox("No PCB document is open.", title, wx.OK | wx.ICON_ERROR)
            return 1

        project_path = getattr(board.document.project, "path", os.getcwd())
        board_name = os.path.splitext(getattr(board.document, "board_filename", "board"))[0]
        default_output_dir = os.path.join(project_path, "{}_multiboard_export".format(board_name))
        settings_path = settings_path_for_board(project_path, board_name)

        dialog = MultiBoardExporterDialog(None, default_output_dir, settings_path=settings_path)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return 0

            try:
                regions = dialog.get_regions()
                output_dir = dialog.get_output_dir()
                export_format = dialog.get_export_format()
            except ValueError as exc:
                wx.MessageBox(str(exc), title, wx.OK | wx.ICON_ERROR)
                return 1
        finally:
            dialog.Destroy()

        log_lines = []

        def logger(message):
            log_lines.append(message)
            print(message)

        outputs = export_regions(
            kicad=kicad,
            source_board=board,
            output_dir=output_dir,
            regions=regions,
            export_step_files=bool(export_format),
            export_format=export_format,
            logger=logger,
        )

        lines = ["Exported {} board(s) to:".format(len(outputs)), output_dir]
        for output in outputs:
            lines.append("")
            lines.append(output["name"])
            lines.append("  PCB: {}".format(output["pcb"]))
            if "step" in output:
                lines.append("  STEP: {}".format(output["step"]))
            if "wrl" in output:
                lines.append("  WRL: {}".format(output["wrl"]))

        wx.MessageBox("\n".join(lines), title, wx.OK | wx.ICON_INFORMATION)
        return 0
    except Exception as exc:
        show_error(title, exc)
        return 1
    finally:
        app.Destroy()


if __name__ == "__main__":
    raise SystemExit(main())
