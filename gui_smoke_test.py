"""Exercise UI callbacks and worker lifecycle without operating other applications."""
import hashlib
from pathlib import Path
import time
import tkinter as tk
import uuid

from archive_studio import ArchiveApp, enable_dpi_awareness

base = Path(__file__).parent / ".test-runs" / ("gui-" + uuid.uuid4().hex[:8])
base.mkdir(parents=True)
source = base / "介面測試.txt"
source.write_text("測試 GUI end to end\n" * 5000, encoding="utf-8")
enable_dpi_awareness()
root = tk.Tk()
root.withdraw()
app = ArchiveApp(root)
root.update()
app.output_chosen = True
app.output.set(str(base / "results"))

def wait():
    end = time.monotonic() + 20
    while app.busy and time.monotonic() < end:
        root.update()
        time.sleep(0.01)
    assert not app.busy, "UI worker timeout"
    assert app.last_result, app.status.cget("text")
    assert app.progress["value"] == 100
    return app.last_result.path

app.add_paths([str(source)])
app.name.set("GUI壓縮")
app.start()
first = wait()
app.switch_mode("convert")
app.add_paths([str(first)])
app.name.set("GUI轉換")
app.format.set("TAR.GZ")
app.refresh_format()
app.start()
second = wait()
app.switch_mode("extract")
app.add_paths([str(second)])
app.start()
third = wait()
assert (third / source.name).read_bytes() == source.read_bytes()
assert str(app.format_combo.cget("state")) == "disabled"
app.switch_mode("compress")
app.format.set("TAR")
app.refresh_format()
assert str(app.level_combo.cget("state")) == "disabled"
app.format.set("ZIP")
app.refresh_format()
assert str(app.level_combo.cget("state")) == "readonly"
root.deiconify()
root.update()
# Verify primary controls fit in the default window at the current DPI.
for widget in (app.start_button, app.cancel_button, app.open_button, app.output_entry,
               app.tree, app.title):
    bottom = widget.winfo_rooty() - root.winfo_rooty() + widget.winfo_height()
    right = widget.winfo_rootx() - root.winfo_rootx() + widget.winfo_width()
    assert bottom <= root.winfo_height(), (widget, bottom, root.winfo_height())
    assert right <= root.winfo_width(), (widget, right, root.winfo_width())
print("GUI callbacks: compress -> convert -> extract OK")
print("Chinese file SHA-256:", hashlib.sha256(source.read_bytes()).hexdigest())
print("Windows native drop hook:", bool(app.drop and app.drop.hwnd))
print("Layout:", root.winfo_width(), "x", root.winfo_height())
app.close()
