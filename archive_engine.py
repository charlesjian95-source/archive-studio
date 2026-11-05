"""Archive Studio engine; never deletes source or partial files."""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import threading
import time
from typing import Callable, NamedTuple
import unicodedata
import zipfile

FORMATS = {"ZIP": ".zip", "TAR": ".tar", "TAR.GZ": ".tar.gz"}
READ_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                 ".tar.xz", ".txz", ".rar")
ARCHIVE_FILTER = "*.zip *.rar *.tar *.gz *.tgz *.bz2 *.tbz2 *.xz *.txz"
MAX_ENTRIES = 100_000
MAX_BYTES = 20 * 1024 ** 3
CHUNK = 1024 * 1024
RESERVE = 64 * 1024 ** 2
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


class ArchiveError(Exception):
    pass


class Cancelled(ArchiveError):
    pass


class PasswordRequired(ArchiveError):
    """Ask for a RAR password on the UI thread, never persist it."""


class Entry(NamedTuple):
    name: str
    is_dir: bool
    size: int
    mtime: float
    opener: Callable | None


class Result(NamedTuple):
    path: Path
    files: int
    original_bytes: int
    output_bytes: int
    seconds: float


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("工作已取消。")


def commit_output(source, target, cancel=None):
    """Allow brief Windows file-sharing locks to clear without replacing a target."""
    delays = (0.05, 0.15, 0.3, 0.6)
    for attempt in range(len(delays) + 1):
        check_cancel(cancel)
        if target.exists():
            raise FileExistsError("輸出位置已存在：" + str(target))
        try:
            source.rename(target)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == len(delays):
                raise
            if cancel is not None:
                cancel.wait(delays[attempt])
            else:
                time.sleep(delays[attempt])


def safe_name(name):
    """One canonical Windows-safe relative path, for every format."""
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ArchiveError("壓縮包包含絕對路徑：" + name)
    name = name.rstrip("/")
    if not name or name == ".":
        return ""
    parts = name.split("/")
    for part in parts:
        if (part in ("", ".", "..") or part[-1:] in (" ", ".")
                or RESERVED.match(part)
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)):
            raise ArchiveError("不支援或不安全的檔案路徑：" + name)
    if len(name) > 2048:
        raise ArchiveError("檔案路徑過長：" + name[:120])
    return "/".join(parts)


def validate(entries):
    seen = {}
    total = 0
    if len(entries) > MAX_ENTRIES:
        raise ArchiveError("單次最多處理 100,000 個項目。")
    for entry in entries:
        name = safe_name(entry.name)
        key = unicodedata.normalize("NFC", name).casefold()
        if not name:
            raise ArchiveError("壓縮包包含無效的空路徑。")
        if key in seen:
            raise ArchiveError("壓縮包內有重複或大小寫衝突的路徑：" + name)
        seen[key] = entry.is_dir
        if entry.size < 0:
            raise ArchiveError("壓縮包的檔案大小無效。")
        total += entry.size
        if total > MAX_BYTES:
            raise ArchiveError("單次未壓縮內容上限為 20 GB。")
    for key in seen:
        parts = key.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i])
            if parent in seen and not seen[parent]:
                raise ArchiveError("壓縮包的檔案與資料夾路徑衝突：" + key)
    return total


def _is_link(path, info=None):
    info = info or path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400)


def collect_inputs(inputs, cancel=None):
    selected = []
    for raw in inputs:
        path = Path(raw).absolute()
        if not path.exists():
            raise ArchiveError("找不到檔案：" + str(path))
        if _is_link(path):
            raise ArchiveError("請選擇實際檔案，不能加入符號連結或接合點：" + str(path))
        path = path.resolve()
        if path not in selected:
            selected.append(path)
    selected = [p for p in selected
                if not any(q != p and q.is_dir() and q in p.parents for q in selected)]
    if not selected:
        raise ArchiveError("請先加入檔案或資料夾。")
    entries = []

    def visit(path, name):
        check_cancel(cancel)
        info = path.lstat()
        if _is_link(path, info):
            raise ArchiveError("資料夾內含符號連結或接合點：" + str(path))
        name = safe_name(name)
        if stat.S_ISDIR(info.st_mode):
            entries.append(Entry(name, True, 0, info.st_mtime, None))
            with os.scandir(path) as scan:
                children = sorted(scan, key=lambda e: e.name.casefold())
            for child in children:
                visit(Path(child.path), name + "/" + child.name)
        elif stat.S_ISREG(info.st_mode):
            entries.append(Entry(name, False, info.st_size, info.st_mtime,
                                 lambda p=path: p.open("rb")))
        else:
            raise ArchiveError("不支援的檔案類型：" + str(path))
        if len(entries) > MAX_ENTRIES:
            raise ArchiveError("單次最多處理 100,000 個項目。")

    for path in selected:
        visit(path, path.name)
    validate(entries)
    return entries


@contextlib.contextmanager
def read_archive(path, cancel=None, password=None):
    path = Path(path)
    entries = []
    with path.open("rb") as probe:
        is_rar = probe.read(8).startswith(b"Rar!\x1a\x07")
    if is_rar or path.suffix.lower() == ".rar":
        from rar_support import read_rar
        with read_rar(path, cancel, password) as entries:
            yield entries
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path, "r") as archive:
            for info in archive.infolist():
                check_cancel(cancel)
                name = safe_name(info.filename)
                if not name and info.is_dir():
                    continue
                mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ArchiveError("壓縮包包含連結或特殊檔案：" + info.filename)
                if info.flag_bits & 1:
                    raise ArchiveError("這個版本尚未支援加密 ZIP，請先用原工具解鎖。")
                try:
                    mtime = dt.datetime(*info.date_time).timestamp()
                except (ValueError, OSError):
                    mtime = time.time()
                entries.append(Entry(name, info.is_dir(), 0 if info.is_dir() else info.file_size,
                                     mtime, None if info.is_dir() else
                                     lambda member=info: archive.open(member, "r")))
                if len(entries) > MAX_ENTRIES:
                    raise ArchiveError("壓縮包項目超過 100,000 個。")
            validate(entries)
            yield entries
    else:
        try:
            archive = tarfile.open(path, "r:*")
        except (tarfile.TarError, EOFError) as exc:
            raise ArchiveError("無法讀取壓縮包，請選擇 ZIP、RAR、TAR 或 TAR.GZ。") from exc
        with archive:
            for info in archive:
                check_cancel(cancel)
                name = safe_name(info.name)
                if not name and info.isdir():
                    continue
                if not (info.isfile() or info.isdir()):
                    raise ArchiveError("壓縮包包含連結或特殊檔案：" + info.name)
                entries.append(Entry(name, info.isdir(), 0 if info.isdir() else info.size,
                                     info.mtime, None if info.isdir() else
                                     lambda member=info: archive.extractfile(member)))
                if len(entries) > MAX_ENTRIES:
                    raise ArchiveError("壓縮包項目超過 100,000 個。")
            validate(entries)
            yield entries


def unique_path(folder, name):
    folder = Path(folder)
    candidate = folder / name
    for n in range(1, 10001):
        if not candidate.exists():
            return candidate
        extension = ".tar.gz" if name.lower().endswith(".tar.gz") else Path(name).suffix
        stem = name[:-len(extension)] if extension else name
        candidate = folder / (stem + " (" + str(n) + ")" + extension)
    raise ArchiveError("同名檔案太多，請換一個輸出名稱。")


def archive_stem(path):
    name = Path(path).name
    for suffix in sorted(READ_SUFFIXES, key=len, reverse=True):
        if name.lower().endswith(suffix):
            return name[:-len(suffix)]
    return Path(name).stem


def archive_name(name, format_name):
    if format_name not in FORMATS:
        raise ArchiveError("請選擇有效的輸出格式。")
    name = (name or "我的壓縮包").strip()
    for suffix in (".tar.gz", ".zip", ".tar"):
        if name.lower().endswith(suffix):
            name = name[:-len(suffix)]
            break
    name = safe_name(name)
    if not name or "/" in name:
        raise ArchiveError("請輸入檔名，不要包含資料夾路徑。")
    return name + FORMATS[format_name]


def _check_space(folder, needed):
    if shutil.disk_usage(folder).free < needed + RESERVE:
        raise ArchiveError("輸出磁碟可用空間不足。")


class Meter:
    def __init__(self, entries, callback, cancel):
        self.total = sum(e.size for e in entries)
        self.count = len(entries)
        self.done = 0
        self.items = 0
        self.callback = callback or (lambda *args: None)
        self.cancel = cancel
        self.current = ""
        self.last = 0.0
        self.entry_done = 0
        self.entry_size = 0

    def begin(self, entry):
        check_cancel(self.cancel)
        self.current = entry.name
        self.entry_size = entry.size
        self.entry_done = 0
        self.emit(True)

    def add(self, count):
        check_cancel(self.cancel)
        self.done += count
        self.entry_done += count
        if self.entry_done > self.entry_size:
            raise ArchiveError("來源檔案大小在處理中改變，請重新執行。")
        self.emit()

    def finish(self):
        if self.entry_done != self.entry_size:
            raise ArchiveError("檔案內容不完整或來源檔案大小已改變：" + self.current)
        self.items += 1
        self.emit(True)

    def emit(self, force=False):
        now = time.monotonic()
        if force or now - self.last > 0.08:
            fraction = self.done / self.total if self.total else self.items / max(1, self.count)
            self.callback(min(0.99, fraction), self.current, self.done, self.total)
            self.last = now


class MeterReader(io.RawIOBase):
    def __init__(self, source, meter):
        self.source = source
        self.meter = meter

    def readable(self):
        return True

    def read(self, size=-1):
        check_cancel(self.meter.cancel)
        data = self.source.read(size)
        self.meter.add(len(data))
        return data


def _copy(source, target, meter):
    while True:
        check_cancel(meter.cancel)
        data = source.read(CHUNK)
        if not data:
            break
        meter.add(len(data))
        target.write(data)


def _write_entries(entries, stream, format_name, level, meter):
    if format_name == "ZIP":
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=level, allowZip64=True) as archive:
            for entry in entries:
                meter.begin(entry)
                stamp = time.localtime(entry.mtime)
                date_time = (max(1980, min(2107, stamp.tm_year)), *stamp[1:6])
                info = zipfile.ZipInfo(entry.name + ("/" if entry.is_dir else ""), date_time)
                info.create_system = 3
                info.external_attr = ((stat.S_IFDIR | 0o755) if entry.is_dir else
                                      (stat.S_IFREG | 0o644)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = level
                info.file_size = entry.size
                if entry.is_dir:
                    info.external_attr |= 0x10
                    archive.writestr(info, b"")
                else:
                    with entry.opener() as source, archive.open(info, "w", force_zip64=True) as dest:
                        _copy(source, dest, meter)
                meter.finish()
    else:
        options = {"compresslevel": level} if format_name == "TAR.GZ" else {}
        with tarfile.open(fileobj=stream, mode="w:gz" if format_name == "TAR.GZ" else "w",
                          format=tarfile.PAX_FORMAT, **options) as archive:
            for entry in entries:
                meter.begin(entry)
                info = tarfile.TarInfo(entry.name)
                info.mtime = entry.mtime
                info.mode = 0o755 if entry.is_dir else 0o644
                info.size = entry.size
                info.type = tarfile.DIRTYPE if entry.is_dir else tarfile.REGTYPE
                if entry.is_dir:
                    archive.addfile(info)
                else:
                    with entry.opener() as source:
                        archive.addfile(info, MeterReader(source, meter))
                meter.finish()


def _write_archive(entries, output_dir, name, format_name, level, progress, cancel):
    started = time.monotonic()
    total = validate(entries)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _check_space(output_dir, total + len(entries) * 2048)
    final = unique_path(output_dir, archive_name(name, format_name))
    partial = unique_path(output_dir, final.name + ".partial")
    meter = Meter(entries, progress, cancel)
    try:
        with partial.open("xb") as stream:
            _write_entries(entries, stream, format_name, int(level), meter)
        check_cancel(cancel)
        if final.exists():
            final = unique_path(output_dir, final.name)
        commit_output(partial, final, cancel)
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        suffix = "\n未完成的檔案已保留在：\n" + str(partial) if partial.exists() else ""
        if isinstance(exc, Cancelled):
            raise Cancelled(message + suffix) from exc
        if isinstance(exc, PasswordRequired):
            raise PasswordRequired(message + suffix) from exc
        raise ArchiveError(message + suffix) from exc
    (progress or (lambda *args: None))(1.0, "完成", total, total)
    return Result(final, sum(not e.is_dir for e in entries), total,
                  final.stat().st_size, time.monotonic() - started)


def compress(inputs, output_dir, name, format_name="ZIP", level=6, progress=None, cancel=None):
    return _write_archive(collect_inputs(inputs, cancel), output_dir, name,
                          format_name, level, progress, cancel)


def convert(source, output_dir, name, format_name="ZIP", level=6, progress=None, cancel=None, password=None):
    with read_archive(source, cancel, password) as entries:
        return _write_archive(entries, output_dir, name, format_name, level, progress, cancel)


def extract(source, output_dir, progress=None, cancel=None, password=None):
    started = time.monotonic()
    with read_archive(source, cancel, password) as entries:
        total = validate(entries)
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        _check_space(output_dir, total)
        final = unique_path(output_dir, archive_stem(source) or "解壓縮")
        staging = unique_path(output_dir, final.name + ".partial")
        staging.mkdir()
        meter = Meter(entries, progress, cancel)
        try:
            for entry in entries:
                meter.begin(entry)
                dest = staging.joinpath(*entry.name.split("/"))
                # No extractall: all targets are checked and no links are created.
                if not dest.resolve().is_relative_to(staging.resolve()):
                    raise ArchiveError("檔案路徑超出輸出資料夾。")
                if entry.is_dir:
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with entry.opener() as src, dest.open("xb") as target:
                        _copy(src, target, meter)
                    with contextlib.suppress(OSError, OverflowError, ValueError):
                        os.utime(dest, (entry.mtime, entry.mtime))
                meter.finish()
            check_cancel(cancel)
            if final.exists():
                final = unique_path(output_dir, final.name)
            commit_output(staging, final, cancel)
        except Exception as exc:
            suffix = "\n未完成的內容已保留在：\n" + str(staging)
            if isinstance(exc, Cancelled):
                raise Cancelled(str(exc) + suffix) from exc
            if isinstance(exc, PasswordRequired):
                raise PasswordRequired(str(exc) + suffix) from exc
            raise ArchiveError((str(exc) or type(exc).__name__) + suffix) from exc
    (progress or (lambda *args: None))(1.0, "完成", total, total)
    return Result(final, sum(not e.is_dir for e in entries), total, total,
                  time.monotonic() - started)
