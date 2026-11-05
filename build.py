"""Build a portable Windows folder and ZIP without deleting earlier builds."""
from pathlib import Path
import datetime as dt
import importlib.metadata
import json
import shutil
import subprocess
import sys
import zipfile
import hashlib
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent


def icon_file(path):
    image = Image.new("RGBA", (256,256))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((3,3,253,253), radius=62, fill="#4f46e5")
    draw.rounded_rectangle((64,47,192,216), radius=20, outline="white", width=15)
    draw.line((128,49,128,160), fill="#c7d2fe", width=14)
    for y in (73,105,137):
        draw.line((111,y,145,y),fill="white",width=10)
    draw.rounded_rectangle((109,161,147,194),radius=9,fill="white")
    image.save(path, format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    image.close()


def main():
    assets = BASE / "assets"
    assets.mkdir(exist_ok=True)
    icon = assets / "studio.ico"
    if not icon.exists():
        icon_file(icon)
    backend = BASE / "vendor" / "unrar" / "UnRAR.exe"
    backend_info = json.loads((BASE / "vendor" / "unrar" / "provenance.json").read_text(encoding="utf-8"))
    if hashlib.sha256(backend.read_bytes()).hexdigest() != backend_info["sha256"]:
        raise RuntimeError("Bundled UnRAR checksum mismatch")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = BASE / ".build" / stamp
    work.mkdir(parents=True)
    dist = BASE / "dist"
    if (dist / "ArchiveStudio").exists():
        dist = dist / stamp
    args = [sys.executable, "-m", "PyInstaller", "--windowed", "--onedir",
            "--name", "ArchiveStudio", "--icon", str(icon),
            "--collect-all", "pi_heif", "--exclude-module", "pillow_heif", "--exclude-module", "_pillow_heif",
            "--exclude-module", "cryptography",
            "--add-binary", str(backend) + ";vendor/unrar",
            "--add-data", str(icon) + ";assets",
            "--distpath", str(dist), "--workpath", str(work / "work"),
            "--specpath", str(work), str(BASE / "archive_studio.py")]
    subprocess.run(args, cwd=BASE, check=True)
    app = dist / "ArchiveStudio"
    shutil.copyfile(BASE / "README.md", app / "使用說明.md")
    licenses = app / "LICENSES"
    licenses.mkdir()
    python_root = Path(sys.base_prefix)
    license_source = python_root / "LICENSE.txt"
    if license_source.exists():
        shutil.copyfile(license_source, licenses / "Python-LICENSE.txt")
    for name in ("tcl8.6", "tk8.6"):
        terms = python_root / "tcl" / name / "license.terms"
        if terms.exists():
            shutil.copyfile(terms, licenses / (name + "-license.terms"))
    for dist_name in ("pyinstaller", "pyinstaller-hooks-contrib", "altgraph",
                      "packaging", "pefile", "pywin32-ctypes", "Pillow", "pi-heif", "rarfile", "pycryptodome"):
        package = importlib.metadata.distribution(dist_name)
        for file in package.files or ():
            lower = str(file).lower()
            if ".dist-info/" in lower and ("license" in lower or lower.endswith("copying.txt")):
                source = Path(package.locate_file(file))
                if source.is_file():
                    target = licenses / dist_name / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copyfile(source, target)
    shutil.copytree(BASE / "vendor" / "unrar", licenses / "UnRAR",
                    ignore=shutil.ignore_patterns("*.exe"))
    (app / "BUILD-INFO.txt").write_text(
        "Archive Studio 1.4.0\nBuilt: " + stamp +
        "\nPython: " + sys.version + "\nPyInstaller: " +
        importlib.metadata.version("pyinstaller") + "\nPillow: " +
        importlib.metadata.version("Pillow") + "\npi-heif: " +
        importlib.metadata.version("pi-heif") + "\nrarfile: " +
        importlib.metadata.version("rarfile") + "\nUnRAR: " + backend_info["version"] + "\n", encoding="utf-8")
    (licenses / "SOURCES.txt").write_text(
        "Python: https://www.python.org/downloads/source/\n"
        "Pillow: https://github.com/python-pillow/Pillow/tree/12.3.0\n"
        "pi-heif: https://github.com/bigcat88/pillow_heif/tree/master/pi-heif\n"
        "libheif: https://github.com/strukturag/libheif\n"
        "Bundled codecs and their licenses: pi-heif/LICENSES_bundled.txt\n"
        "rarfile: https://github.com/markokr/rarfile/tree/v4.2\n"
        "PyCryptodome: https://github.com/Legrandin/pycryptodome\n"
        "UnRAR: https://www.rarlab.com/rar_add.htm (see UnRAR/provenance.json)\n", encoding="utf-8")
    (app / "加入右鍵選單.cmd").write_text('@echo off\r\n"%~dp0ArchiveStudio.exe" --register-shell\r\n', encoding="ascii")
    zip_path = dist / "ArchiveStudio-1.4.0-Windows-x64.zip"
    with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for item in sorted(app.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(dist))
    (BASE / "dist" / "latest.json").write_text(json.dumps({
        "version": "1.4.0", "app": str(app), "exe": str(app / "ArchiveStudio.exe"),
        "zip": str(zip_path), "built": stamp}, indent=2), encoding="utf-8")
    print("APP:", app / "ArchiveStudio.exe")
    print("PORTABLE ZIP:", zip_path)


if __name__ == "__main__":
    main()
