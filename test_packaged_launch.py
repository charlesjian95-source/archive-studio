"""Verify launch routing against the packaged executable, not the source interpreter."""
from pathlib import Path
import json
import subprocess
import sys
import time
import archive_engine as engine
from PIL import Image
import photo_engine

base = Path(__file__).parent
manifest = json.loads((base / "dist" / "latest.json").read_text(encoding="utf-8"))
exe = manifest["exe"]
folder = base / ".test-runs" / ("packaged-launch-" + str(time.time_ns()))
folder.mkdir(parents=True)
source = folder / "中文 資料夾 & 測試"
source.mkdir()
(source / "作業.txt").write_text("資料保留\n" * 100, encoding="utf-8")
archive = engine.compress([source], folder, "作業 壓縮包").path
cases = [("compress", ["--compress"], source), ("extract", ["--extract"], archive),
         ("convert", ["--convert"], archive), ("extract", [], archive)]
photo = folder / "iPhone 中文照片.heic"
photo.write_bytes((base / "testdata" / "heic-sample.heic").read_bytes())
cases.extend([("photos", ["--photos"], photo), ("photos", [], photo)])
for index, (mode, flags, path) in enumerate(cases):
    report = folder / ("%s-%s.json" % (index, mode))
    completed = subprocess.run([exe, "--diagnostic", str(report), *flags, "--", str(path)],
                               timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["mode"] == mode, data
    assert data["paths"] == [str(path)], data
    assert data["rows"][0][0] == path.name, data
    assert data["start_button_visible"], data
    print("Packaged EXE:", mode, "imported", path.name, "scale", data["scale"])
print("Packaged Unicode and spaced-path launch checks: OK")
report = folder / "photo-actual-conversion.json"
completed = subprocess.run([exe, "--diagnostic", str(report), "--diagnostic-run", "--photos", "--", str(photo)],
                           timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
assert completed.returncode == 0
data = json.loads(report.read_text(encoding="utf-8"))
assert data["files"] == 1 and not data["failures"], data
assert "AVIF" in data["codecs"], data
with Image.open(next(Path(data["result"]).glob("*.jpg"))) as converted:
    assert converted.size == (120, 80)
print("Packaged EXE: real HEIC -> JPEG conversion OK")
