"""Stream RAR3/RAR5 members through the bundled official UnRAR reader.

UnRAR only writes to stdout; Archive Studio validates and creates every path.
No extraction temporary files, shell commands, or user-installed tools are used.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import stat
import sys
import threading
import time

import rarfile

from archive_engine import ArchiveError, Cancelled, Entry, MAX_ENTRIES, PasswordRequired
from archive_engine import check_cancel, safe_name, validate


BACKEND = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "vendor" / "unrar" / "UnRAR.exe"
rarfile.UNRAR_TOOL = str(BACKEND)
# rarfile's optional speed hack creates and removes temporary archives.
# Disable it to preserve the app's no-automatic-deletion behavior.
rarfile.USE_EXTRACT_HACK = False
_setup_lock = threading.Lock()


def setup_backend():
    if not BACKEND.is_file():
        raise ArchiveError("缺少 RAR 解壓元件，請完整解壓縮最新版程式，保留 _internal 資料夾。")
    with _setup_lock:
        rarfile.tool_setup(unrar=True, unar=False, bsdtar=False,
                           sevenzip=False, sevenzip2=False)


def rar_error(exc, password=None):
    if isinstance(exc, (rarfile.PasswordRequired, rarfile.RarWrongPassword)):
        return PasswordRequired("請輸入 RAR 密碼。" if password is None else "RAR 密碼不正確，請重新輸入。")
    if isinstance(exc, rarfile.NeedFirstVolume):
        return ArchiveError("這是 RAR 分卷的中間檔案。請將所有分卷放在同一資料夾，並選擇第一卷（part1.rar 或 .rar）。")
    if isinstance(exc, rarfile.RarCannotExec):
        return ArchiveError("無法啟動 RAR 解壓元件。請完整解壓縮最新版程式，保留 _internal 資料夾。")
    if "Cannot open next volume" in str(exc) or isinstance(exc, rarfile.RarOpenError):
        return ArchiveError("無法讀取 RAR 或缺少分卷。請將所有分卷放在同一資料夾，從第一卷開始。")
    if isinstance(exc, rarfile.BadRarFile) and password is not None:
        return ArchiveError("RAR 密碼不正確或內容已損壞；請確認密碼與所有分卷。")
    return ArchiveError("無法讀取 RAR，檔案可能損壞或使用不支援的功能。\n" + (str(exc) or type(exc).__name__))


class MemberReader:
    """Bound one member to its declared size without closing the shared pipe."""
    def __init__(self, sequence, info):
        self.sequence = sequence
        self.remaining = info.file_size
        self.hash = (info._md_class or rarfile.NoHashContext)()
        self.expected = info._md_expect

    def read(self, size=-1):
        check_cancel(self.sequence.cancel)
        count = self.remaining if size is None or size < 0 else min(size, self.remaining)
        parts = []
        while count:
            check_cancel(self.sequence.cancel)
            data = self.sequence.process.stdout.read(min(count, 1024 * 1024))
            if not data:
                self.sequence.check_exit()
                raise ArchiveError("RAR 檔案內容不完整。")
            self.hash.update(data)
            parts.append(data)
            self.remaining -= len(data)
            count -= len(data)
        return b"".join(parts)


class RarSequence:
    """One stdout stream in archive order, including solid archives.

This avoids repeatedly decoding solid blocks and avoids the Windows legacy
filename code page conversion that occurs when selecting members by name.
"""
    def __init__(self, path, members, cancel, password):
        self.path, self.members = path, members
        self.cancel, self.password = cancel, password
        self.process = None
        self.index = 0
        self.stopped = threading.Event()
        self.watcher = None

    def start(self):
        check_cancel(self.cancel)
        cmd = rarfile.tool_setup().open_cmdline(self.password, str(self.path))
        self.process = rarfile.custom_popen(cmd)
        if self.cancel is not None:
            def watch():
                while not self.stopped.wait(.05):
                    if self.cancel.is_set():
                        with contextlib.suppress(OSError):
                            self.process.kill()
                        return
            self.watcher = threading.Thread(target=watch, daemon=True)
            self.watcher.start()

    def check_exit(self):
        code = self.process.wait()
        check_cancel(self.cancel)
        rarfile.check_returncode(code, "", rarfile.UNRAR_CONFIG["errmap"])

    @contextlib.contextmanager
    def member(self, info):
        check_cancel(self.cancel)
        if self.index >= len(self.members) or self.members[self.index] is not info:
            raise ArchiveError("RAR 必須依壓縮包內的順序讀取。")
        try:
            if self.process is None:
                self.start()
            reader = MemberReader(self, info)
            yield reader
            check_cancel(self.cancel)
            if reader.remaining:
                raise ArchiveError("RAR 檔案內容未完整讀取。")
            if reader.expected is not None and reader.hash.digest() != reader.expected:
                raise ArchiveError("RAR 內容檢查失敗，檔案可能已損壞：" + info.filename)
            self.index += 1
            if self.index == len(self.members):
                if self.process.stdout.read(1):
                    raise ArchiveError("RAR 解壓內容超過檔案標示的大小。")
                self.check_exit()
        except rarfile.Error as exc:
            check_cancel(self.cancel)
            raise rar_error(exc, self.password) from exc

    def close(self):
        self.stopped.set()
        if self.watcher is not None:
            self.watcher.join(timeout=1)
        if self.process is not None:
            if self.process.poll() is None:
                with contextlib.suppress(OSError):
                    self.process.kill()
            self.process.stdout.close()
            self.process.wait()


@contextlib.contextmanager
def read_rar(path, cancel=None, password=None):
    check_cancel(cancel)
    count = 0

    def on_header(info):
        nonlocal count
        check_cancel(cancel)
        if info.type == rarfile.RAR_BLOCK_FILE:
            count += 1
            if count > MAX_ENTRIES:
                raise ArchiveError("壓縮包項目超過 100,000 個。")

    try:
        setup_backend()
        with rarfile.RarFile(path, errors="strict", crc_check=True, info_callback=on_header) as archive:
            if archive.needs_password():
                if password is None:
                    raise PasswordRequired("這個 RAR 已加密，請輸入密碼以繼續。")
                archive.setpassword(password)
            entries = []
            members = []
            for info in archive.infolist():
                check_cancel(cancel)
                try:
                    # Legacy RAR3 can expose UTF-16 surrogate pairs as two code
                    # points. Canonicalize them before writing ZIP or file paths.
                    filename = info.filename.encode("utf-16", "surrogatepass").decode("utf-16")
                except UnicodeError as exc:
                    raise ArchiveError("RAR 包含無法讀取的檔案名稱。") from exc
                name = safe_name(filename)
                if not name and info.is_dir():
                    continue
                if (info.is_symlink() or info.file_redir is not None
                        or not (info.is_file() or info.is_dir())
                        or (info.host_os == rarfile.RAR_OS_UNIX
                            and stat.S_IFMT(info.mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                    raise ArchiveError("壓縮包包含連結或特殊檔案：" + info.filename)
                try:
                    mtime = info.mtime.timestamp() if info.mtime else time.time()
                except (ValueError, OSError, OverflowError):
                    mtime = time.time()
                entries.append(Entry(name, info.is_dir(), 0 if info.is_dir() else info.file_size,
                                     mtime, None if info.is_dir() else
                                     lambda member=info: sequence.member(member)))
                if not info.is_dir():
                    members.append(info)
            validate(entries)
            sequence = RarSequence(path, members, cancel, password)
            try:
                yield entries
            finally:
                sequence.close()
    except rarfile.Error as exc:
        check_cancel(cancel)
        raise rar_error(exc, password) from exc
