"""Per-user Explorer integration. Adds owned entries, never changes UserChoice."""
from pathlib import Path
import ctypes
import json
import os
import subprocess
import sys

ARCHIVE_EXTENSIONS = (".zip", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz")
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".dib", ".tif", ".tiff", ".gif", ".heic", ".heif", ".avif")
CLASSES = r"Software\Classes"


def registration_plan(executable):
    executable = str(Path(executable).resolve())
    if '"' in executable:
        raise ValueError("Invalid executable path")
    prefix = '"' + executable + '"'
    plan = []
    def value(path, name, data):
        plan.append((CLASSES + "\\" + path, name, data))
    def verb(base, identifier, label, flag):
        path = base + "\\shell\\" + identifier
        value(path, "", label)
        value(path, "Icon", executable + ",0")
        value(path + "\\command", "", prefix + " " + flag + ' -- "%1"')
    for base in ("*", "Directory"):
        verb(base, "ArchiveStudio.Compress", "使用 Archive Studio 壓縮", "--compress")
    verb("Directory", "ArchiveStudio.Photos", "使用 Archive Studio 轉換照片", "--photos")
    for extension in PHOTO_EXTENSIONS:
        verb("SystemFileAssociations\\" + extension, "ArchiveStudio.Photos", "使用 Archive Studio 轉換照片", "--photos")
    for extension in ARCHIVE_EXTENSIONS:
        base = r"SystemFileAssociations" + "\\" + extension
        verb(base, "ArchiveStudio.Extract", "使用 Archive Studio 解壓縮", "--extract")
        verb(base, "ArchiveStudio.Convert", "使用 Archive Studio 轉換格式", "--convert")
    application = r"Applications\ArchiveStudio.exe"
    value(application, "FriendlyAppName", "Archive Studio 檔案工具")
    value(application + r"\DefaultIcon", "", executable + ",0")
    value(application + r"\shell\open\command", "", prefix + ' -- "%1"')
    value("ArchiveStudio.Archive", "", "Archive Studio 壓縮包")
    value(r"ArchiveStudio.Archive\DefaultIcon", "", executable + ",0")
    value(r"ArchiveStudio.Archive\shell\open\command", "", prefix + ' --extract -- "%1"')
    for extension in ARCHIVE_EXTENSIONS:
        value(application + r"\SupportedTypes", extension, "")
        value(extension + r"\OpenWithProgids", "ArchiveStudio.Archive", "")
    value("ArchiveStudio.Photo", "", "Archive Studio 照片")
    value(r"ArchiveStudio.Photo\DefaultIcon", "", executable + ",0")
    value(r"ArchiveStudio.Photo\shell\open\command", "", prefix + ' --photos -- "%1"')
    for extension in PHOTO_EXTENSIONS:
        value(application + r"\SupportedTypes", extension, "")
        value(extension + r"\OpenWithProgids", "ArchiveStudio.Photo", "")
    return plan


def register(executable=None):
    if sys.platform != "win32":
        raise RuntimeError("這項功能只支援 Windows。")
    import winreg
    if executable is None:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("請從打包完成的 ArchiveStudio.exe 加入右鍵選單。")
        executable = sys.executable
    executable = Path(executable).resolve(strict=True)
    plan = registration_plan(executable)
    # Record only the values this app owns, for inspection; no default handler is changed.
    config = Path(os.environ["LOCALAPPDATA"]) / "ArchiveStudio"
    config.mkdir(parents=True, exist_ok=True)
    record = config / "windows-integration.json"
    previous = []
    for key_path, name, value in plan:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                old, kind = winreg.QueryValueEx(key, name)
            previous.append({"key": key_path, "name": name, "previous": old, "type": kind})
        except FileNotFoundError:
            previous.append({"key": key_path, "name": name, "previous": None})
    snapshot = config / ("integration-before-" + str(__import__("time").time_ns()) + ".json")
    snapshot.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    for key_path, name, value in plan:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    # Pass data through environment variables; never interpolate paths into PowerShell code.
    script = """$ErrorActionPreference = 'Stop'
$programs = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $programs 'Archive Studio 壓縮工具.lnk'))
$shortcut.TargetPath = $env:ARCHIVE_STUDIO_EXE
$shortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($env:ARCHIVE_STUDIO_EXE)
$shortcut.IconLocation = $env:ARCHIVE_STUDIO_EXE + ',0'
$shortcut.Description = 'ZIP 壓縮、RAR 解壓縮、照片轉檔、HEIC 轉 JPG'
$shortcut.Save()
$photoShortcut = $shell.CreateShortcut((Join-Path $programs 'Archive Studio 照片轉檔.lnk'))
$photoShortcut.TargetPath = $env:ARCHIVE_STUDIO_EXE
$photoShortcut.Arguments = '--photos'
$photoShortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($env:ARCHIVE_STUDIO_EXE)
$photoShortcut.IconLocation = $env:ARCHIVE_STUDIO_EXE + ',0'
$photoShortcut.Description = '批次照片轉檔、HEIC、JPG、PNG、WebP、AVIF'
$photoShortcut.Save()
"""
    environment = os.environ.copy()
    environment["ARCHIVE_STUDIO_EXE"] = str(executable)
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    completed = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                               env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
                               capture_output=True)
    if completed.returncode:
        raise RuntimeError("右鍵選單已加入，但開始功能表捷徑更新失敗。")
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    record.write_text(json.dumps({"executable": str(executable), "entries": len(plan),
                                 "snapshot": str(snapshot)}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return {"executable": str(executable), "registry_values": len(plan), "record": str(record)}


if __name__ == "__main__":
    print(json.dumps(register(sys.argv[1] if len(sys.argv) > 1 else None), ensure_ascii=False))
