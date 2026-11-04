"""Integration tests retain their fixtures under .test-runs; no automatic deletion."""
import hashlib
import io
from pathlib import Path
import stat
import tarfile
import threading
import time
import unittest
import uuid
import warnings
from unittest.mock import patch
import zipfile

import archive_engine as engine


class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = Path(__file__).parent / ".test-runs" / (
            time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
        cls.fixtures.mkdir(parents=True)

    def setUp(self):
        self.base = self.fixtures / self._testMethodName
        self.base.mkdir()
        self.src = self.base / "中文資料"
        self.src.mkdir()
        (self.src / "空資料夾").mkdir()
        (self.src / "nested").mkdir()
        (self.src / "說明.txt").write_text("你好，世界！\n" * 4000, encoding="utf-8")
        (self.src / "nested" / "data.bin").write_bytes(bytes(range(256)) * 800)
        (self.src / "zero.txt").write_bytes(b"")
        self.out = self.base / "out"
        self.out.mkdir()

    def manifest(self, root):
        return {p.relative_to(root).as_posix():
                ("directory" if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
                for p in root.rglob("*")}

    def make_zip(self, names):
        path = self.base / "unsafe.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w") as archive:
                for name in names:
                    archive.writestr(name, b"test")
        return path

    def test_all_round_trips_and_conversion_matrix(self):
        original = self.manifest(self.src)
        for source_format in engine.FORMATS:
            first = engine.compress([self.src], self.out, "測試 " + source_format, source_format)
            self.assertTrue(first.path.exists())
            self.assertEqual(first.files, 3)
            for target_format in engine.FORMATS:
                target = engine.convert(first.path, self.out,
                                        source_format + " to " + target_format, target_format)
                result = engine.extract(target.path, self.out)
                self.assertEqual(original, self.manifest(result.path / self.src.name))
        self.assertEqual(original, self.manifest(self.src))

    def test_empty_archives(self):
        source = self.base / "empty.zip"
        with zipfile.ZipFile(source, "w"):
            pass
        converted = engine.convert(source, self.out, "empty", "TAR.GZ")
        result = engine.extract(converted.path, self.out)
        self.assertEqual(result.files, 0)
        self.assertEqual(list(result.path.iterdir()), [])

    def test_collision_never_overwrites(self):
        first = engine.compress([self.src], self.out, "same")
        before = first.path.read_bytes()
        second = engine.compress([self.src], self.out, "same")
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(first.path.read_bytes(), before)
        a = engine.extract(first.path, self.out)
        b = engine.extract(first.path, self.out)
        self.assertNotEqual(a.path, b.path)
        self.assertEqual(self.manifest(a.path), self.manifest(b.path))

    def test_parent_selection_deduplicates_children(self):
        result = engine.compress([self.src / "說明.txt", self.src, self.src], self.out, "parent")
        self.assertEqual(result.files, 3)

    def test_duplicate_root_names_are_rejected(self):
        other = self.base / "other" / self.src.name
        other.mkdir(parents=True)
        with self.assertRaises(engine.ArchiveError):
            engine.compress([self.src, other], self.out, "ambiguous")

    def test_rejects_unsafe_names_before_writing(self):
        names = ("../escape", "/absolute", "C:/escape", "a\\..\\escape",
                 "a:stream", "NUL.txt", "folder/COM1", "trailing. ", "a//b")
        for name in names:
            archive = self.base / (uuid.uuid4().hex + ".zip")
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr(name, b"bad")
            with self.assertRaises(engine.ArchiveError, msg=name):
                engine.extract(archive, self.out)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_rejects_duplicate_and_conflicting_entries(self):
        for names in (("A.txt", "a.txt"), ("same", "same"), ("file", "file/child")):
            archive = self.make_zip(names)
            with self.assertRaises(engine.ArchiveError):
                engine.extract(archive, self.out)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_rejects_tar_links_and_special_files(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            path = self.base / (uuid.uuid4().hex + ".tar")
            with tarfile.open(path, "w") as archive:
                item = tarfile.TarInfo("link")
                item.type = kind
                item.linkname = "../outside"
                archive.addfile(item)
            with self.assertRaises(engine.ArchiveError):
                engine.extract(path, self.out)
            with self.assertRaises(engine.ArchiveError):
                engine.convert(path, self.out, "must not convert")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_rejects_zip_symlink(self):
        path = self.base / "link.zip"
        with zipfile.ZipFile(path, "w") as archive:
            item = zipfile.ZipInfo("link")
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, "../escape")
        with self.assertRaises(engine.ArchiveError):
            engine.extract(path, self.out)

    def test_cancel_before_start(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(engine.Cancelled):
            engine.compress([self.src], self.out, "cancelled", cancel=cancel)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_cancel_during_write_retains_partial_and_source(self):
        cancel = threading.Event()
        before = self.manifest(self.src)

        def callback(fraction, name, done, total):
            if done:
                cancel.set()

        with self.assertRaises(engine.Cancelled):
            engine.compress([self.src], self.out, "cancelled",
                            progress=callback, cancel=cancel)
        self.assertTrue(list(self.out.glob("*.partial")))
        self.assertFalse(list(self.out.glob("*.zip")))
        self.assertEqual(before, self.manifest(self.src))

    def test_cancel_during_extract_retains_partial(self):
        source = engine.compress([self.src], self.out, "source")
        cancel = threading.Event()

        def callback(fraction, name, done, total):
            if done:
                cancel.set()

        with self.assertRaises(engine.Cancelled):
            engine.extract(source.path, self.out, progress=callback, cancel=cancel)
        self.assertTrue(any(p.is_dir() for p in self.out.glob("*.partial")))

    def test_progress_and_compression(self):
        events = []
        result = engine.compress([self.src], self.out, "progress", progress=lambda *v: events.append(v))
        self.assertEqual(events[-1][0], 1)
        self.assertEqual(events[-1][2], result.original_bytes)
        self.assertLess(result.output_bytes, result.original_bytes)
        self.assertTrue(all(a[0] <= b[0] for a, b in zip(events, events[1:])))

    def test_standard_tar_root_and_long_unicode_names(self):
        source = self.base / "standard.tar.gz"
        name = "nested/" + "中文" * 65 + ".txt"
        with tarfile.open(source, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            root = tarfile.TarInfo(".")
            root.type = tarfile.DIRTYPE
            archive.addfile(root)
            item = tarfile.TarInfo("./" + name)
            item.size = 5
            archive.addfile(item, io.BytesIO(b"hello"))
        converted = engine.convert(source, self.out, "long names", "ZIP")
        with zipfile.ZipFile(converted.path) as reader:
            self.assertEqual(reader.read(name), b"hello")

    def test_corrupt_archive_and_resource_limits(self):
        source = self.base / "corrupt.zip"
        source.write_bytes(b"this is not an archive")
        with self.assertRaises(engine.ArchiveError):
            engine.extract(source, self.out)
        with self.assertRaises(engine.ArchiveError):
            engine.validate([engine.Entry("huge", False, engine.MAX_BYTES + 1, 0, None)])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_crc_errors_leave_partial(self):
        source = self.base / "crc.zip"
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("file.txt", b"PAYLOAD_CONTENT")
        raw = source.read_bytes().replace(b"PAYLOAD_CONTENT", b"BROKEN__CONTENT", 1)
        source.write_bytes(raw)
        with self.assertRaises(engine.ArchiveError):
            engine.extract(source, self.out)
        self.assertTrue(list(self.out.glob("*.partial")))

    def test_does_not_require_extracting_conversion_to_disk(self):
        archive = engine.compress([self.src], self.out, "source")
        before = {p.name for p in self.out.iterdir()}
        result = engine.convert(archive.path, self.out, "converted", "TAR.GZ")
        self.assertEqual({p.name for p in self.out.iterdir()} - before, {result.path.name})

    def test_brief_windows_sharing_lock_is_retried(self):
        source = self.out / "ready.partial"
        source.write_bytes(b"complete")
        final = self.out / "ready.zip"
        rename = Path.rename
        attempts = []
        def locked_then_ready(path, target):
            attempts.append(path)
            if len(attempts) < 3:
                error = PermissionError("sharing violation")
                error.winerror = 32
                raise error
            return rename(path, target)
        with patch.object(Path, "rename", locked_then_ready):
            engine.commit_output(source, final)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(final.read_bytes(), b"complete")

    def test_cancel_while_waiting_for_lock_preserves_partial(self):
        source = self.out / "ready.partial"
        source.write_bytes(b"complete")
        final = self.out / "ready.zip"
        cancel = threading.Event()
        def locked(path, target):
            cancel.set()
            error = PermissionError("sharing violation")
            error.winerror = 32
            raise error
        with patch.object(Path, "rename", locked):
            with self.assertRaises(engine.Cancelled):
                engine.commit_output(source, final, cancel)
        self.assertTrue(source.exists())
        self.assertFalse(final.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
