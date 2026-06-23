import os
import json

import wx


HEADERS = (
    "Name",
    "X min",
    "Y min",
    "X max",
    "Y max",
    "Origin X",
    "Origin Y",
)

EXPORT_FORMATS = (
    ("step", "STEP"),
    ("wrl", "WRL"),
    ("", "None"),
)


class MultiBoardExporterDialog(wx.Dialog):
    def __init__(self, parent, default_output_dir, settings_path=None):
        super(MultiBoardExporterDialog, self).__init__(
            parent,
            title="Multi-board Geometry Exporter",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.default_output_dir = default_output_dir
        self.settings_path = settings_path
        self.rows = []

        self.output_dir = wx.DirPickerCtrl(
            self,
            path=default_output_dir,
            message="Choose output directory",
            style=wx.DIRP_USE_TEXTCTRL,
        )
        self.export_format = wx.Choice(
            self,
            choices=[label for _value, label in EXPORT_FORMATS],
        )
        self.export_format.SetSelection(0)

        self.grid = wx.FlexGridSizer(0, len(HEADERS), 6, 6)
        self.grid.AddGrowableCol(0, 1)

        for header in HEADERS:
            label = wx.StaticText(self, label=header)
            self.grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)

        self.add_button = wx.Button(self, label="Add Board")
        self.remove_button = wx.Button(self, label="Remove Last")

        self.add_button.Bind(wx.EVT_BUTTON, self.on_add_board)
        self.remove_button.Bind(wx.EVT_BUTTON, self.on_remove_last)

        buttons = wx.StdDialogButtonSizer()
        export_button = wx.Button(self, wx.ID_OK, "Export")
        apply_button = wx.Button(self, wx.ID_APPLY, "Apply")
        cancel_button = wx.Button(self, wx.ID_CANCEL, "Cancel")
        buttons.AddButton(export_button)
        buttons.AddButton(apply_button)
        buttons.AddButton(cancel_button)
        buttons.Realize()

        export_button.Bind(wx.EVT_BUTTON, self.on_export)
        apply_button.Bind(wx.EVT_BUTTON, self.on_apply)

        top = wx.BoxSizer(wx.VERTICAL)

        output_box = wx.BoxSizer(wx.VERTICAL)
        output_box.Add(wx.StaticText(self, label="Output directory"), 0, wx.BOTTOM, 4)
        output_box.Add(self.output_dir, 0, wx.EXPAND)

        format_row = wx.BoxSizer(wx.HORIZONTAL)
        format_row.Add(wx.StaticText(self, label="Geometry export"), 0, wx.ALIGN_CENTER_VERTICAL)
        format_row.Add(self.export_format, 0, wx.LEFT, 8)
        output_box.Add(format_row, 0, wx.TOP, 8)

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        toolbar.Add(self.add_button, 0)
        toolbar.Add(self.remove_button, 0, wx.LEFT, 8)

        top.Add(output_box, 0, wx.ALL | wx.EXPAND, 12)
        top.Add(toolbar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        top.Add(self.grid, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        if buttons:
            top.Add(buttons, 0, wx.ALL | wx.EXPAND, 12)

        self.SetSizer(top)

        if not self.load_settings():
            self.add_board("Board_A", -0.5, -50.5, 40.5, 0.5, 0.0, 0.0)
            self.add_board("Board_B", 46.5, -25.5, 67.5, 0.5, 47.0, 0.0)

        self.SetMinSize((760, 320))
        self.Fit()

    def add_board(self, name=None, xmin=0.0, ymin=0.0, xmax=10.0, ymax=10.0,
                  origin_x=0.0, origin_y=0.0):
        index = len(self.rows) + 1
        values = [
            name or "Board_{}".format(index),
            xmin,
            ymin,
            xmax,
            ymax,
            origin_x,
            origin_y,
        ]

        controls = []
        for value in values:
            ctrl = wx.TextCtrl(self, value=str(value))
            controls.append(ctrl)
            self.grid.Add(ctrl, 0, wx.EXPAND)

        self.rows.append(controls)
        self.Layout()
        self.Fit()

    def on_add_board(self, _event):
        self.add_board()

    def on_remove_last(self, _event):
        if len(self.rows) <= 1:
            return

        controls = self.rows.pop()
        for ctrl in controls:
            self.grid.Detach(ctrl)
            ctrl.Destroy()

        self.Layout()
        self.Fit()

    def on_apply(self, _event):
        if self.save_settings_with_feedback():
            wx.MessageBox("Settings saved.", self.GetTitle(), wx.OK | wx.ICON_INFORMATION)

    def on_export(self, _event):
        if self.save_settings_with_feedback():
            self.EndModal(wx.ID_OK)

    def get_regions(self):
        regions = []

        for row_index, controls in enumerate(self.rows, start=1):
            name = controls[0].GetValue().strip() or "Board_{}".format(row_index)
            try:
                numbers = [float(ctrl.GetValue()) for ctrl in controls[1:]]
            except ValueError:
                raise ValueError("Board '{}' has a non-numeric coordinate.".format(name))

            xmin, ymin, xmax, ymax, origin_x, origin_y = numbers
            if xmin == xmax or ymin == ymax:
                raise ValueError("Board '{}' has an empty bounding box.".format(name))

            regions.append(
                {
                    "name": name,
                    "bbox": (xmin, ymin, xmax, ymax),
                    "new_origin": (origin_x, origin_y),
                }
            )

        return regions

    def get_output_dir(self):
        path = self.output_dir.GetPath().strip()
        if not path:
            path = self.default_output_dir
        return os.path.abspath(path)

    def get_export_format(self):
        selection = self.export_format.GetSelection()
        if selection == wx.NOT_FOUND:
            return "step"
        return EXPORT_FORMATS[selection][0] or None

    def should_export_step(self):
        return self.get_export_format() == "step"

    def save_settings_with_feedback(self):
        try:
            self.save_settings()
            return True
        except ValueError as exc:
            wx.MessageBox(str(exc), self.GetTitle(), wx.OK | wx.ICON_ERROR)
            return False
        except Exception as exc:
            wx.MessageBox(
                "Could not save settings:\n\n{}".format(exc),
                self.GetTitle(),
                wx.OK | wx.ICON_ERROR,
            )
            return False

    def settings_data(self):
        return {
            "output_dir": self.get_output_dir(),
            "export_format": self.get_export_format(),
            "regions": self.get_regions(),
        }

    def save_settings(self):
        if not self.settings_path:
            return

        settings_dir = os.path.dirname(self.settings_path)
        if settings_dir:
            os.makedirs(settings_dir, exist_ok=True)

        with open(self.settings_path, "w", encoding="utf-8") as settings_file:
            json.dump(self.settings_data(), settings_file, indent=2, sort_keys=True)

    def load_settings(self):
        if not self.settings_path or not os.path.isfile(self.settings_path):
            return False

        try:
            with open(self.settings_path, "r", encoding="utf-8") as settings_file:
                data = json.load(settings_file)

            output_dir = data.get("output_dir")
            if output_dir:
                self.output_dir.SetPath(output_dir)

            export_format = data.get("export_format")
            if export_format is False:
                export_format = None
            elif export_format is True:
                export_format = "step"

            regions = data.get("regions") or []
            loaded_rows = []
            for region in regions:
                bbox = region.get("bbox") or (0.0, 0.0, 10.0, 10.0)
                new_origin = region.get("new_origin") or (0.0, 0.0)
                loaded_rows.append(
                    (
                        region.get("name"),
                        bbox[0],
                        bbox[1],
                        bbox[2],
                        bbox[3],
                        new_origin[0],
                        new_origin[1],
                    )
                )

            if not loaded_rows:
                return False

            self.set_export_format(export_format or "")
            for row in loaded_rows:
                self.add_board(*row)

            return True
        except Exception:
            return False

    def set_export_format(self, value):
        for index, (format_value, _label) in enumerate(EXPORT_FORMATS):
            if format_value == (value or ""):
                self.export_format.SetSelection(index)
                return
        self.export_format.SetSelection(0)
