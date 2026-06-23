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

        dialog = MultiBoardExporterDialog(None, default_output_dir)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return 0

            try:
                regions = dialog.get_regions()
                output_dir = dialog.get_output_dir()
                export_step = dialog.should_export_step()
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
            export_step_files=export_step,
            logger=logger,
        )

        lines = ["Exported {} board(s) to:".format(len(outputs)), output_dir]
        for output in outputs:
            lines.append("")
            lines.append(output["name"])
            lines.append("  PCB: {}".format(output["pcb"]))
            if "step" in output:
                lines.append("  STEP: {}".format(output["step"]))

        wx.MessageBox("\n".join(lines), title, wx.OK | wx.ICON_INFORMATION)
        return 0
    except Exception as exc:
        show_error(title, exc)
        return 1
    finally:
        app.Destroy()


if __name__ == "__main__":
    raise SystemExit(main())
