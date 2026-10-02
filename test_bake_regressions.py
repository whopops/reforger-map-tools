"""Regression checks for installation and foliage dependency failures."""
import builtins
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rmtlib import fieldmap, foliage


class BakeRegressionTests(unittest.TestCase):
    def test_install_replaces_changed_content_with_identical_size_and_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder, "src"); dst = Path(folder, "dst")
            src.mkdir(); dst.mkdir()
            a = src / "tile.bin"; b = dst / "tile.bin"
            a.write_bytes(b"NEW"); b.write_bytes(b"OLD")
            st = a.stat(); os.utime(b, ns=(st.st_atime_ns, st.st_mtime_ns))
            fieldmap.copy_tree(str(src), str(dst), folder, lambda _: None)
            self.assertEqual(b.read_bytes(), b"NEW")
            # A second edit with the original timestamps must not hit filecmp's cache.
            a.write_bytes(b"NOW"); os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns))
            fieldmap.copy_tree(str(src), str(dst), folder, lambda _: None)
            self.assertEqual(b.read_bytes(), b"NOW")

    def test_install_keeps_identical_files_without_copying(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder, "src"); dst = Path(folder, "dst")
            src.mkdir(); dst.mkdir()
            (src / "tile.bin").write_bytes(b"same"); (dst / "tile.bin").write_bytes(b"same")
            with patch.object(fieldmap.shutil, "copy2", side_effect=AssertionError("copied unchanged file")):
                fieldmap.copy_tree(str(src), str(dst), folder, lambda _: None)

    def test_missing_scipy_fails_before_reading_shots_or_writing_profiles(self):
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == "scipy" or name.startswith("scipy."):
                raise ModuleNotFoundError("No module named scipy")
            return original(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as folder, patch("builtins.__import__", side_effect=missing):
            with self.assertRaisesRegex(RuntimeError, "requires SciPy"):
                foliage.analyse(folder)
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
