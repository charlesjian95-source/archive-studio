"""Exercise the photo workflow, preview, failure recovery, and DPI layouts."""
import json
from pathlib import Path
import time
import tkinter as tk
from unittest.mock import patch

from PIL import Image

from archive_studio import ArchiveApp, enable_dpi_awareness

enable_dpi_awareness()
base = Path(__file__).parent / ".test-runs" / ("photo-ui-" + str(time.time_ns()))
base.mkdir(parents=True)
album = base / "中文相簿"
album.mkdir()
for name, color in (("photo & space.png", "red"), ("第二張.png", "blue")):
    with Image.new("RGB", (240, 120), color) as image:
        image.save(album / name)
(album / "壞檔.jpg").write_bytes(b"not an image")
(album / "notes.txt").write_text("not a photo", encoding="utf-8")
reports = []


def wait(root, condition, label):
    deadline = time.monotonic() + 20
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(.01)
    assert condition(), label
    root.update()


def layout(root, app, case):
    root.update()
    panel = app.photo_panel
    controls = [app.brand, *app.nav.values(), app.start_button, app.result_button,
                app.open_button, panel.tree, panel.canvas, panel.preset_combo, panel.format_combo,
                panel.quality_slider, panel.resize_combo, panel.background_combo, panel.output_entry,
                panel.add_button, panel.folder_button, panel.remove_button, panel.clear_button,
                panel.metadata_button, panel.browse_button, panel.zoom_button]
    for widget in controls:
        assert widget.winfo_ismapped(), (case, str(widget), "not mapped")
        left = widget.winfo_rootx() - root.winfo_rootx()
        top = widget.winfo_rooty() - root.winfo_rooty()
        right, bottom = left + widget.winfo_width(), top + widget.winfo_height()
        assert min(left, top) >= 0 and right <= root.winfo_width() and bottom <= root.winfo_height(), (
            case, str(widget), (left, top, right, bottom), root.winfo_geometry())
    assert panel.tree.winfo_height() >= app.px(65), (case, "queue too short", panel.tree.winfo_height())
    assert panel.canvas.winfo_height() >= app.px(140), (case, "preview too short", panel.canvas.winfo_height())
    assert panel.canvas.winfo_width() >= app.px(210), (case, "preview too narrow", panel.canvas.winfo_width())
    controls = [panel.add_button, panel.folder_button, panel.remove_button, panel.clear_button]
    positions = [(w.winfo_rootx(), w.winfo_rootx() + w.winfo_width()) for w in controls]
    for index, a in enumerate(positions):
        for b in positions[index + 1:]:
            assert a[1] <= b[0] or b[1] <= a[0], (case, "overlapping toolbar", a, b)
    reports.append({"case": case, "window": [root.winfo_width(), root.winfo_height()],
                    "queue_height": panel.tree.winfo_height(), "preview_height": panel.canvas.winfo_height()})


for scale in (1.0, 1.5, 2.0):
    root = tk.Tk()
    app = ArchiveApp(root, ui_scale=scale, persist_preferences=False)
    app.switch_mode("photos")
    panel = app.photo_panel
    assert str(app.start_button.cget("state")) == "disabled"
    app.add_paths([str(album)])
    wait(root, lambda: not panel.loading, "folder discovery timed out")
    assert len(panel.sources) == 3
    assert len(panel.tree.get_children()) == 3
    assert "略過 1" in panel.count.cget("text")
    assert str(app.start_button.cget("state")) == "normal"
    panel.tree.selection_set("0")
    panel.schedule_preview()
    wait(root, lambda: panel.preview_data is not None, "image preview timed out")
    assert panel.preview_data.original_size == (240, 120)
    panel.show_preview()
    root.update()
    previews = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(previews) == 1
    previews[0].destroy()
    panel.preset.set("網頁 WebP · 較小檔案")
    panel.apply_preset()
    assert panel.options().format == "WebP"
    assert panel.options().quality == 80
    assert panel.options().max_edge == 1920
    panel.preset.set("通用 JPG · 高畫質")
    panel.apply_preset()
    layout(root, app, "%s-default" % scale)
    root.geometry("%dx%d" % root.minsize())
    layout(root, app, "%s-minimum" % scale)
    root.state("zoomed")
    layout(root, app, "%s-maximized" % scale)
    panel.output.set(str(base / ("out-" + str(scale))))
    app.start()
    assert app.busy
    assert all(str(button.cget("state")) == "disabled" for button in app.nav.values())
    wait(root, lambda: not app.busy, "photo batch timed out")
    assert panel.result.files == 2, panel.result
    assert panel.result.failures == 1
    assert "失敗" in app.status.cget("text")
    assert str(app.result_button.cget("state")) == "normal"
    assert str(app.open_button.cget("state")) == "normal"
    assert any(panel.tree.item(i, "values")[2] == "失敗" for i in panel.tree.get_children())
    panel.show_results()
    root.update()
    result_windows = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(result_windows) == 1
    result_windows[0].destroy()
    # Preferences are round-tripped only through a fixture file, never user settings.
    panel.persist = True
    panel.preferences = base / ("preferences-" + str(scale) + ".json")
    panel.quality.set(84)
    panel.save_preferences()
    panel.quality.set(40)
    panel._load_preferences()
    assert panel.quality.get() == 84
    panel.tree.selection_set(panel.tree.get_children())
    panel.remove_selected()
    assert not panel.sources
    assert panel.preview_data is None
    assert (album / "photo & space.png").exists()
    assert str(app.start_button.cget("state")) == "disabled"
    app.close()

(base / "layout-report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
print(json.dumps(reports, indent=2))
print("Photo UI: preview, presets, mixed-success batch, results, preferences, queue removal, DPI: OK")
