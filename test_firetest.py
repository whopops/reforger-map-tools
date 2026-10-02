"""Terrain-loading regression; run with python -B -m unittest test_firetest.py."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import firetest


class TerrainTests(unittest.TestCase):
    def test_near_classifies_objects_from_kind_not_bottom_height(self):
        n = 1000 * 1000
        top, bottom, kind = bytearray(n), bytearray(n), bytearray(n)
        # Solid objects have underside 0; an elevated empty cell deliberately
        # has a height that would be mistaken for an object type by the old code.
        for x, object_kind in ((10, 1), (20, 2), (30, 3), (40, 5)):
            index = 20 * 1000 + x * 2
            top[index], kind[index] = 8, object_kind
        bottom[20 * 1000 + 100] = 2
        raw = bytes(501 * 501 * 2) + top + bottom + kind + bytes(n)

        with tempfile.TemporaryDirectory() as site:
            folder = Path(site, "maps", "everon", "los")
            folder.mkdir(parents=True)
            (folder / "index.json").write_text(json.dumps({"tiles": ["0_0"], "terrain": {"unit": 0.01}}))
            (folder / "0_0.bin.gz").write_bytes(gzip.compress(raw))
            with patch.object(firetest, "SITE", site):
                terrain = firetest.Terrain()
                self.assertTrue(terrain.near(10, 10, r=0))
                self.assertTrue(terrain.near(20, 10, r=0))
                self.assertFalse(terrain.near(30, 10, r=0))
                self.assertTrue(terrain.near(30, 10, r=0, kinds=(3,)))
                self.assertTrue(terrain.near(40, 10, r=0, kinds=(5,)))
                self.assertFalse(terrain.near(50, 10, r=0))
                self.assertEqual(terrain.ground(10, 10), 0)


if __name__ == "__main__":
    unittest.main()
