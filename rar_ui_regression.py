"""Exercise the actual RAR worker, modal password response, retry and cancel UI."""
from pathlib import Path
import time
import tkinter as tk
from unittest.mock import patch
import uuid

from archive_studio import ArchiveApp, enable_dpi_awareness

base = Path(__file__).parent
output = base / ".test-runs" / ("rar-ui-" + uuid.uuid4().hex)
output.mkdir(parents=True)
fixtures = base / "testdata" / "rar"
enable_dpi_awareness()
root = tk.Tk()
root.withdraw()
app = ArchiveApp(root, persist_preferences=False)
app.output_chosen = True
app.output.set(str(output))
errors = []


def wait():
    deadline = time.monotonic() + 15
    while app.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(.01)
    assert not app.busy, "RAR UI worker timeout"


try:
    with patch("archive_studio.messagebox.showerror", side_effect=lambda *a, **k: errors.append(a)):
        app.switch_mode("extract")
        app.add_paths([str(fixtures / "rar5-solid.rar")])
        app.start()
        wait()
        assert app.last_result and app.last_result.files == 2
        app.switch_mode("convert")
        app.add_paths([str(fixtures / "rar3-solid.rar")])
        app.start()
        wait()
        assert app.last_result and app.last_result.path.suffix == ".zip"
        app.switch_mode("extract")
        for name in ("rar5-psw.rar", "rar5-hpsw.rar", "rar3-comment-hpsw.rar"):
            app.add_paths([str(fixtures / name)])
            with patch("archive_studio.simpledialog.askstring", return_value="password") as dialog:
                app.start()
                wait()
                assert dialog.call_count == 1
                assert dialog.call_args.kwargs["show"] == "●"
            assert app.last_result and app.last_result.files > 0, (name, errors)
        app.add_paths([str(fixtures / "rar5-hpsw.rar")])
        with patch("archive_studio.simpledialog.askstring", side_effect=["wrong", "password"]) as dialog:
            app.start()
            wait()
            assert dialog.call_count == 2
        assert app.last_result and app.last_result.files == 2
        with patch("archive_studio.simpledialog.askstring", return_value=None):
            app.start()
            wait()
        assert app.last_result is None
        assert "取消輸入密碼" in app.status.cget("text")
        assert str(app.start_button.cget("state")) == "normal"
        assert not errors, errors
    print("RAR UI: extract, ZIP conversion, data/header passwords, wrong-password retry and cancel OK")
finally:
    app.close()
