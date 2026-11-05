"""RAR interoperability against upstream rarfile 4.2 fixtures and official UnRAR."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile
from types import SimpleNamespace

import rarfile
import archive_engine as engine
import rar_support

FIXTURES = Path(__file__).parent / "testdata" / "rar"


class RarTests(unittest.TestCase):
    def setUp(self):
        self.output = Path(__file__).parent / ".test-runs" / ("rar-" + uuid.uuid4().hex)
        self.output.mkdir(parents=True)

    def manifest(self, path):
        return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in path.rglob("*") if p.is_file()}

    def test_fixture_and_backend_integrity(self):
        manifest = json.loads((FIXTURES / "SOURCES.json").read_text(encoding="utf-8"))
        for name, expected in manifest["files"].items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), expected)
        manifest = json.loads((rar_support.BACKEND.parent / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(rar_support.BACKEND.read_bytes()).hexdigest(), manifest["sha256"])

    def test_rar3_and_rar5_unicode_subdirs_and_empty_directory(self):
        manifests = []
        for version in (3, 5):
            result = engine.extract(FIXTURES / f"rar{version}-subdirs.rar", self.output)
            self.assertEqual(result.files, 4)
            self.assertTrue((result.path / "sub" / "empty").is_dir())
            self.assertEqual((result.path / "sub/dir1/file1.txt").read_bytes(), b"file1\n")
            manifests.append(self.manifest(result.path))
        self.assertEqual(*manifests)

    def test_solid_rar_converts_to_every_output_format(self):
        for version in (3, 5):
            source = FIXTURES / f"rar{version}-solid.rar"
            original = source.read_bytes()
            expected = self.manifest(engine.extract(source, self.output).path)
            for fmt in engine.FORMATS:
                converted = engine.convert(source, self.output, f"solid-{version}-{fmt}", fmt)
                actual = self.manifest(engine.extract(converted.path, self.output).path)
                self.assertEqual(expected, actual)
            self.assertEqual(source.read_bytes(), original)

    def test_legacy_non_bmp_names_can_convert_to_zip(self):
        source = FIXTURES / "unicode.rar"
        result = engine.convert(source, self.output, "unicode", "ZIP")
        with zipfile.ZipFile(result.path) as archive:
            self.assertEqual(len(archive.namelist()), 2)
            self.assertTrue(all(archive.read(n) for n in archive.namelist()))

    def test_password_data_and_encrypted_headers(self):
        for name in ("rar5-psw.rar", "rar5-hpsw.rar", "rar3-comment-hpsw.rar"):
            source = FIXTURES / name
            with self.assertRaises(engine.PasswordRequired):
                engine.extract(source, self.output)
            result = engine.extract(source, self.output, password="password")
            self.assertGreater(result.files, 0)
            converted = engine.convert(source, self.output, name, password="password")
            unpacked = engine.extract(converted.path, self.output)
            self.assertEqual(self.manifest(result.path), self.manifest(unpacked.path))

    def test_wrong_password_never_reports_success(self):
        for name in ("rar5-psw.rar", "rar5-hpsw.rar", "rar3-comment-hpsw.rar"):
            with self.assertRaises(engine.ArchiveError):
                engine.extract(FIXTURES / name, self.output, password="wrong")
        self.assertTrue(all(p.name.endswith(".partial") for p in self.output.iterdir()))

    def test_rar3_and_rar5_multiple_volumes(self):
        results = []
        for version in (3, 5):
            source = FIXTURES / f"rar{version}-vols.part1.rar"
            result = engine.extract(source, self.output)
            self.assertGreater(result.original_bytes, source.stat().st_size)
            results.append(self.manifest(result.path))
            with self.assertRaisesRegex(engine.ArchiveError, "第一卷"):
                engine.extract(FIXTURES / f"rar{version}-vols.part2.rar", self.output)
        self.assertEqual(*results)

    def test_missing_volume_fails_before_writing(self):
        source = self.output / "rar5-vols.part1.rar"
        source.write_bytes((FIXTURES / source.name).read_bytes())
        with self.assertRaisesRegex(engine.ArchiveError, "分卷"):
            engine.extract(source, self.output / "results")
        self.assertFalse((self.output / "results").exists())

    def test_links_rejected_before_output_creation(self):
        for name in ("rar3-symlink-unix.rar", "rar5-symlink-win.rar", "rar5-hlink.rar"):
            with self.assertRaisesRegex(engine.ArchiveError, "連結"):
                engine.extract(FIXTURES / name, self.output)
            with self.assertRaises(engine.ArchiveError):
                engine.convert(FIXTURES / name, self.output, "unsafe")
        self.assertEqual(list(self.output.iterdir()), [])

    def test_unsafe_names_and_conflicts_rejected_before_output_creation(self):
        source = FIXTURES / "rar5-subdirs.rar"
        original = rar_support.safe_name
        for name in ("../escape", "C:/escape", "NUL.txt", "a:stream"):
            with patch.object(rar_support, "safe_name", side_effect=lambda _, n=name: original(n)):
                with self.assertRaises(engine.ArchiveError):
                    engine.extract(source, self.output)
        with patch.object(rar_support, "safe_name", return_value="duplicate"):
            with self.assertRaises(engine.ArchiveError):
                engine.extract(source, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_crc_error_and_truncation_never_report_success(self):
        source = FIXTURES / "rar5-crc.rar"
        data = bytearray(source.read_bytes())
        with rarfile.RarFile(source) as archive:
            first = archive.infolist()[0]
            data[first.data_offset + first.compress_size // 2] ^= 0xAA
        corrupt = self.output / "corrupt.rar"
        corrupt.write_bytes(data)
        with self.assertRaises(engine.ArchiveError):
            engine.extract(corrupt, self.output)
        truncated = self.output / "truncated.rar"
        truncated.write_bytes(source.read_bytes()[:40])
        with self.assertRaises(engine.ArchiveError):
            engine.extract(truncated, self.output)

    def test_cancel_retains_partial_and_source(self):
        source = FIXTURES / "rar5-solid.rar"
        before = source.read_bytes()
        cancel = threading.Event()
        def progress(fraction, name, done, total):
            if done:
                cancel.set()
        with self.assertRaises(engine.Cancelled):
            engine.extract(source, self.output, progress=progress, cancel=cancel)
        self.assertTrue(list(self.output.glob("*.partial")))
        self.assertEqual(source.read_bytes(), before)

    def test_renamed_rar_detected_by_signature_and_collision_preserved(self):
        source = self.output / "中文 壓縮包.data"
        source.write_bytes((FIXTURES / "rar5-solid.rar").read_bytes())
        first = engine.extract(source, self.output)
        second = engine.extract(source, self.output)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(self.manifest(first.path), self.manifest(second.path))
        self.assertEqual(engine.archive_stem("photo.RAR"), "photo")
        with self.assertRaises(engine.ArchiveError):
            engine.archive_name("new", "RAR")

    def test_cancel_interrupts_a_blocked_decoder_pipe(self):
        rar_support.setup_backend()
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        cancel = threading.Event()
        timer = threading.Timer(.15, cancel.set)
        started = time.monotonic()
        try:
            with patch.object(rarfile, "custom_popen", return_value=process):
                timer.start()
                with self.assertRaises(engine.Cancelled):
                    engine.extract(FIXTURES / "rar5-solid.rar", self.output, cancel=cancel)
            self.assertLess(time.monotonic() - started, 3)
            self.assertIsNotNone(process.poll())
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()

    def test_decoder_final_error_prevents_committing_complete_sized_output(self):
        source = FIXTURES / "rar5-solid.rar"
        expected = engine.extract(source, self.output / "expected").path
        contents = b"".join((expected / name).read_bytes() for name in ("stest1.txt", "stest2.txt"))
        decoder = SimpleNamespace(stdout=io.BytesIO(contents), wait=lambda: 3, poll=lambda: 3)
        with patch.object(rarfile, "custom_popen", return_value=decoder):
            with self.assertRaises(engine.ArchiveError):
                engine.convert(source, self.output, "must-not-commit")
        self.assertFalse((self.output / "must-not-commit.zip").exists())
        self.assertTrue((self.output / "must-not-commit.zip.partial").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
