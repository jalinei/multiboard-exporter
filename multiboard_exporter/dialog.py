import os

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


class MultiBoardExporterDialog(wx.Dialog):
    def __init__(self, parent, default_output_dir):
        super(MultiBoardExporterDialog, self).__init__(
            parent,
            title="Multi-board Geometry Exporter",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.default_output_dir = default_output_dir
        self.rows = []

        self.output_dir = wx.DirPickerCtrl(
            self,
            path=default_output_dir,
            message="Choose output directory",
            style=wx.DIRP_USE_TEXTCTRL,
        )
        self.export_step = wx.CheckBox(self, label="Export STEP geometry with kicad-cli")
        self.export_step.SetValue(True)

        self.grid = wx.FlexGridSizer(0, len(HEADERS), 6, 6)
        self.grid.AddGrowableCol(0, 1)

        for header in HEADERS:
            label = wx.StaticText(self, label=header)
            self.grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)

        self.add_button = wx.Button(self, label="Add Board")
        self.remove_button = wx.Button(self, label="Remove Last")

        self.add_button.Bind(wx.EVT_BUTTON, self.on_add_board)
        self.remove_button.Bind(wx.EVT_BUTTON, self.on_remove_last)

        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        ok = self.FindWindowById(wx.ID_OK)
        if ok:
            ok.SetLabel("Export")

        top = wx.BoxSizer(wx.VERTICAL)

        output_box = wx.BoxSizer(wx.VERTICAL)
        output_box.Add(wx.StaticText(self, label="Output directory"), 0, wx.BOTTOM, 4)
        output_box.Add(self.output_dir, 0, wx.EXPAND)
        output_box.Add(self.export_step, 0, wx.TOP, 8)

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        toolbar.Add(self.add_button, 0)
        toolbar.Add(self.remove_button, 0, wx.LEFT, 8)

        top.Add(output_box, 0, wx.ALL | wx.EXPAND, 12)
        top.Add(toolbar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        top.Add(self.grid, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        if buttons:
            top.Add(buttons, 0, wx.ALL | wx.EXPAND, 12)

        self.SetSizer(top)

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

    def should_export_step(self):
        return self.export_step.GetValue()
