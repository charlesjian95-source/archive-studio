"""Regression checks for DPI clipping, useful expansion, and imported selection visibility."""
from pathlib import Path
import json
import time
import tkinter as tk
import tkinter.font as tkfont
from unittest.mock import patch
import uuid

from archive_studio import ArchiveApp, enable_dpi_awareness

enable_dpi_awareness()
base = Path(__file__).parent / ".test-runs" / ("layout-" + uuid.uuid4().hex[:8])
base.mkdir(parents=True)
source = base / "中文路徑 含空白 & data.txt"
source.write_text("test", encoding="utf-8")
reports = []


def check(root, app, label):
    root.update()
    root.update_idletasks()
    controls = [app.brand, *app.nav.values(), app.start_button, app.cancel_button,
                app.open_button, app.output_entry, app.tree, app.name_label,
                app.format_combo, app.level_combo, app.add_button, app.clear_button,
                app.remove_button, app.integration_button, app.format_note, app.drop_hint]
    for widget in controls:
        if app.compact and widget in (app.format_note, app.drop_hint):
            continue
        assert widget.winfo_ismapped(), (label, widget, "not mapped")
        left = widget.winfo_rootx() - root.winfo_rootx()
        top = widget.winfo_rooty() - root.winfo_rooty()
        right = left + widget.winfo_width()
        bottom = top + widget.winfo_height()
        assert left >= 0 and top >= 0, (label, str(widget), left, top)
        assert right <= root.winfo_width() and bottom <= root.winfo_height(), (
            label, str(widget), right, bottom, root.winfo_width(), root.winfo_height())
        if isinstance(widget, tk.Label) or widget in app.nav.values():
            assert widget.winfo_width() >= widget.winfo_reqwidth(), (
                label, widget.cget("text"), widget.winfo_width(), widget.winfo_reqwidth())
    buttons = [app.add_button, app.folder_button, app.remove_button, app.clear_button]
    visible = [w for w in buttons if w.winfo_ismapped()]
    rectangles = [(w.winfo_rootx(), w.winfo_rootx()+w.winfo_width()) for w in visible]
    for i, a in enumerate(rectangles):
        for b in rectangles[i+1:]:
            assert a[1] <= b[0] or b[1] <= a[0], (label, "overlapping toolbar", a, b)
    assert app.tree.winfo_height() >= app.px(65), (label, "file list too short")
    reports.append({"case": label, "window": [root.winfo_width(), root.winfo_height()],
                    "file_list_height": app.tree.winfo_height(), "scale": app.scale})


for scale in (1.0, 1.5, 2.0):
    root = tk.Tk()
    root.withdraw()
    app = ArchiveApp(root, ui_scale=scale, launch=("compress", [str(source)]))
    root.deiconify()
    check(root, app, "%s-default" % scale)
    assert list(app.tree.item("0", "values"))[0] == source.name
    assert app.selections["compress"] == [str(source)]
    minimum = root.minsize()
    root.geometry("%dx%d" % minimum)
    check(root, app, "%s-minimum" % scale)
    small_tree = app.tree.winfo_height()
    root.state("zoomed")
    root.update()
    check(root, app, "%s-maximized" % scale)
    assert app.tree.winfo_height() > small_tree + app.px(20)
    for mode in ("extract", "convert"):
        app.switch_mode(mode)
        app.add_paths([str(source)])
        check(root, app, "%s-%s" % (scale, mode))
        assert len(app.tree.get_children()) == 1
    app.close()

# Missing paths must never disappear silently.
root = tk.Tk()
root.withdraw()
app = ArchiveApp(root)
with patch("archive_studio.messagebox.showerror") as error:
    app.add_paths([str(base / "missing.txt")])
    error.assert_called_once()
app.close()
(base / "layout-report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
print(json.dumps(reports, indent=2))
print("DPI layouts, toolbar overlap, maximized expansion, and path import: OK")
