import hashlib
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import photo_engine as photos
from archive_engine import ArchiveError


class PhotoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_folder = Path(__file__).parent / ".test-runs" / ("photos-" + str(time.time_ns()))
        cls.run_folder.mkdir(parents=True)

    def setUp(self):
        self.base = self.run_folder / self._testMethodName
        self.base.mkdir()
        self.source = self.base / "中文照片 & 空白.png"
        with Image.new("RGB", (240, 120), "#da5c42") as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((50, 20, 190, 100), fill="#447bc2")
            image.save(self.source)
        self.output = self.base / "output"

    def convert(self, inputs=None, **options):
        found = photos.discover(inputs or [self.source])
        return photos.convert_batch(found.sources, self.output, photos.Options(**options))

    def test_every_output_format_reopens_and_has_expected_size(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        for name in photos.available_formats():
            with self.subTest(format=name):
                result = self.convert(format=name, max_edge=100)
                self.assertEqual(result.files, 1, result.items)
                self.assertEqual(result.failures, 0)
                with Image.open(result.items[0].output) as image:
                    image.load()
                    self.assertEqual(image.size, (100, 50))
                    expected = photos.FORMATS[name][0]
                    self.assertEqual(image.format, expected)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_heic_input_converts_to_jpg(self):
        source = self.base / "iPhone 照片.heic"
        source.write_bytes((Path(__file__).parent / "testdata" / "heic-sample.heic").read_bytes())
        result = self.convert([source])
        self.assertEqual(result.files, 1, result.items)
        with Image.open(result.items[0].output) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (120, 80))

    def test_exif_orientation_and_metadata(self):
        source = self.base / "rotated.jpg"
        exif = Image.Exif()
        exif[274] = 6
        exif[36867] = "2026:11:04 12:34:56"
        with Image.new("RGB", (100, 200), "red") as image:
            image.save(source, exif=exif)
        for keep in (True, False):
            result = self.convert([source], keep_metadata=keep, max_edge=100)
            with Image.open(result.items[0].output) as image:
                self.assertEqual(image.size, (100, 50))
                self.assertNotIn(274, image.getexif())
                self.assertEqual(36867 in image.getexif(), keep)

    def test_metadata_is_removed_for_lossless_outputs_too(self):
        source = self.base / "with-exif.png"
        exif = Image.Exif()
        exif[315] = "PRIVATE_AUTHOR"
        with Image.new("RGB", (100, 100), "green") as image:
            image.save(source, exif=exif)
        for fmt in ("PNG", "WebP", "TIFF"):
            result = self.convert([source], format=fmt, keep_metadata=False)
            self.assertEqual(result.files, 1, result.items)
            with Image.open(result.items[0].output) as image:
                self.assertNotIn(315, image.getexif())

    def test_alpha_retention_and_explicit_jpg_background(self):
        source = self.base / "transparent.png"
        with Image.new("RGBA", (64, 64), (255, 0, 0, 0)) as image:
            image.save(source)
        result = self.convert([source], format="PNG")
        with Image.open(result.items[0].output) as image:
            self.assertEqual(image.getpixel((32, 32))[3], 0)
        for background, expected in (("white", 255), ("black", 0)):
            result = self.convert([source], background=background)
            with Image.open(result.items[0].output) as image:
                self.assertTrue(all(abs(channel - expected) <= 1 for channel in image.getpixel((32, 32))))

    def test_no_upscale_and_original_size_option(self):
        for edge in (0, 1920):
            result = self.convert(max_edge=edge)
            with Image.open(result.items[0].output) as image:
                self.assertEqual(image.size, (240, 120))

    def test_batch_continues_after_corrupt_photo(self):
        bad = self.base / "bad.jpg"
        bad.write_bytes(b"not a photo")
        more = self.base / "another.png"
        more.write_bytes(self.source.read_bytes())
        result = self.convert([self.source, bad, more])
        self.assertEqual(result.files, 2)
        self.assertEqual(result.failures, 1)
        self.assertEqual([item.status for item in result.items], ["done", "error", "done"])

    def test_animation_and_multipage_are_never_silently_flattened(self):
        source = self.base / "animated.gif"
        with Image.new("RGB", (16, 16), "red") as first, Image.new("RGB", (16, 16), "blue") as second:
            first.save(source, save_all=True, append_images=[second], duration=100, loop=0)
        result = self.convert([source])
        self.assertEqual(result.files, 0)
        self.assertIn("動畫", result.items[0].message)

    def test_folder_structure_and_duplicate_roots(self):
        folder = self.base / "相簿"
        (folder / "子資料夾").mkdir(parents=True)
        photo = folder / "子資料夾" / "照片.png"
        photo.write_bytes(self.source.read_bytes())
        (folder / "notes.txt").write_text("keep", encoding="utf-8")
        found = photos.discover([photo, folder, folder])
        self.assertEqual(len(found.sources), 1)
        self.assertEqual(found.skipped, 1)
        result = photos.convert_batch(found.sources, self.output)
        self.assertTrue((result.path / "相簿" / "子資料夾" / "照片.jpg").exists())

    def test_collisions_do_not_overwrite_outputs_or_sources(self):
        a = self.base / "same.png"
        b = self.base / "same.bmp"
        with Image.new("RGB", (20, 20), "red") as image:
            image.save(a)
            image.save(b)
        originals = {path: path.read_bytes() for path in (a, b)}
        first = self.convert([a, b])
        self.assertNotEqual(first.items[0].output, first.items[1].output)
        second = self.convert([a, b])
        self.assertNotEqual(first.path, second.path)
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data)

    def test_cancel_preserves_completed_results(self):
        extra = self.base / "extra.png"
        extra.write_bytes(self.source.read_bytes())
        cancel = threading.Event()
        found = photos.discover([self.source, extra])
        result = photos.convert_batch(found.sources, self.output, cancel=cancel,
                                      item_callback=lambda *args: cancel.set())
        self.assertTrue(result.cancelled)
        self.assertEqual(result.files, 1)
        self.assertTrue(result.items[0].output.exists())
        self.assertEqual(result.items[1].status, "pending")

    def test_cancel_while_saving_retains_identifiable_partial(self):
        cancel = threading.Event()
        save = Image.Image.save
        def save_and_cancel(image, *args, **kwargs):
            value = save(image, *args, **kwargs)
            cancel.set()
            return value
        with patch.object(Image.Image, "save", save_and_cancel):
            result = photos.convert_batch(photos.discover([self.source]).sources, self.output,
                                          cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.files, 0)
        self.assertEqual(len(list(result.path.rglob("*.partial"))), 1)
        self.assertTrue(self.source.exists())

    def test_preview_matches_saved_dimensions_and_file_size(self):
        options = photos.Options("JPG", 82, 100)
        preview = photos.preview(self.source, options)
        result = photos.convert_batch(photos.discover([self.source]).sources, self.output, options)
        self.assertEqual(preview.output_size, (100, 50))
        self.assertEqual(preview.original_size, (240, 120))
        self.assertEqual(preview.output_bytes, result.output_bytes)
        preview.before.close()
        preview.after.close()

    def test_invalid_options_fail_before_creating_output(self):
        for options in (photos.Options("INVALID"), photos.Options(quality=101), photos.Options(max_edge=-1)):
            with self.assertRaises(ArchiveError):
                photos.convert_batch(photos.discover([self.source]).sources, self.output, options)
        self.assertFalse(self.output.exists())

    def test_relative_path_cannot_escape_output(self):
        result = photos.convert_batch([photos.Source(self.source, Path("../outside.png"))], self.output)
        self.assertEqual(result.files, 0)
        self.assertEqual(result.failures, 1)
        self.assertFalse((self.output / "outside.jpg").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
