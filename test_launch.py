import unittest
from pathlib import Path
from tempfile import gettempdir
from archive_studio import parse_launch
from windows_integration import registration_plan, ARCHIVE_EXTENSIONS, PHOTO_EXTENSIONS

class LaunchTests(unittest.TestCase):
    def test_context_modes_and_exact_unicode_paths(self):
        path = str(Path(gettempdir()) / "中文 資料夾 & literal.txt")
        for flag, expected in (("--compress", "compress"), ("--extract", "extract"), ("--convert", "convert"), ("--photos", "photos")):
            args, (mode, paths) = parse_launch([flag, "--", path])
            self.assertEqual(mode, expected)
            self.assertEqual(paths, [path])

    def test_no_arguments_is_empty_compress(self):
        self.assertEqual(parse_launch([])[1], ("compress", []))

    def test_rar_launch_and_right_click(self):
        path = Path(__file__).parent / "testdata" / "rar" / "rar5-solid.rar"
        self.assertEqual(parse_launch([str(path)])[1], ("extract", [str(path)]))
        self.assertEqual(parse_launch(["--convert", str(path)])[1], ("convert", [str(path)]))
        self.assertIn(".rar", ARCHIVE_EXTENSIONS)
        plan = registration_plan(str(Path.cwd() / "ArchiveStudio.exe"))
        commands = [value for key, name, value in plan if "\\.rar\\" in key and key.endswith("\\command")]
        self.assertTrue(any("--extract" in value for value in commands))
        self.assertTrue(any("--convert" in value for value in commands))

    def test_auto_detect_archive_without_extension_case_assumption(self):
        # Use an existing harmless file to exercise detection; no implicit extraction starts.
        path = Path(__file__).parent / ".test-runs" / "auto-detect.ZIP"
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            path.write_bytes(b"")
        self.assertEqual(parse_launch([str(path)])[1], ("extract", [str(path)]))

    def test_registration_commands_quote_paths_and_route_modes(self):
        exe = str(Path.cwd() / "中文 app" / "ArchiveStudio.exe")
        plan = registration_plan(exe)
        commands = {key: value for key, name, value in plan if key.endswith("\\command")}
        self.assertEqual(len(commands), 2 + 2 * len(ARCHIVE_EXTENSIONS) + 2 + len(PHOTO_EXTENSIONS) + 2)
        for command in commands.values():
            self.assertTrue(command.startswith('"' + exe + '" '))
            self.assertTrue(command.endswith('-- "%1"'))
        self.assertTrue(any("--compress" in v for k, v in commands.items() if "\\Directory\\" in k))
        self.assertTrue(any("--photos" in v for k, v in commands.items() if "\\.heic\\" in k))

    def test_auto_detect_photos_without_changing_explicit_compress(self):
        path = Path(__file__).parent / ".test-runs" / "auto-photo.HEIC"
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            path.write_bytes(b"")
        self.assertEqual(parse_launch([str(path)])[1], ("photos", [str(path)]))
        self.assertEqual(parse_launch(["--compress", str(path)])[1], ("compress", [str(path)]))

    def test_registration_does_not_take_over_default_associations(self):
        for key, name, value in registration_plan(str(Path.cwd() / "ArchiveStudio.exe")):
            self.assertNotIn("UserChoice", key)
            self.assertFalse(any(key == "Software\\Classes\\" + ext and not name for ext in ARCHIVE_EXTENSIONS))
            self.assertTrue(key.startswith("Software\\Classes\\"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
