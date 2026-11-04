"""Inspect release integrity and check output using Windows' independent tar reader."""
from pathlib import Path
import hashlib
import json
import subprocess
import time
import zipfile
import archive_engine as engine

base = Path(__file__).parent
manifest = json.loads((base / "dist" / "latest.json").read_text(encoding="utf-8"))
app = Path(manifest["app"])
package = Path(manifest["zip"])
assert (app / "ArchiveStudio.exe").read_bytes().startswith(b"MZ")
assert (app / "_internal" / "python310.dll").exists()
assert (app / "_internal" / "assets" / "studio.ico").exists()
assert (app / "LICENSES" / "Python-LICENSE.txt").exists()
with zipfile.ZipFile(package) as archive:
    assert archive.testzip() is None
    assert "ArchiveStudio/ArchiveStudio.exe" in archive.namelist()
    assert "ArchiveStudio/BUILD-INFO.txt" in archive.namelist()
check = base / ".test-runs" / ("release-" + str(time.time_ns()))
check.mkdir(parents=True)
source = check / "portable.txt"
source.write_text("independent reader check\n" * 100, encoding="utf-8")
for fmt in engine.FORMATS:
    result = engine.compress([source], check, "reader-" + fmt, fmt)
    target = check / fmt
    target.mkdir()
    subprocess.run(["tar.exe", "-xf", str(result.path), "-C", str(target)], check=True,
                   capture_output=True)
    assert hashlib.sha256((target / source.name).read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest()
print(json.dumps({"release_zip_bytes": package.stat().st_size,
                  "release_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                  "windows_tar_compatibility": "ZIP, TAR, TAR.GZ: OK",
                  "portable_zip_crc": "OK"}, indent=2))
