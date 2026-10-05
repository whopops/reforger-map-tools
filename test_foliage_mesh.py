"""The mesh-based foliage measurement (rmtlib/foliage_mesh.py, xob.py, edds.py) and kind_profiles' use of it."""
import csv
import math
import os
import tempfile
import unittest

import numpy as np

from rmtlib import bake_plants, edds, foliage_mesh


def _game():
    try:
        from rmtlib import pak
        return bool(pak.game_paks())
    except Exception:
        return False


class SliceNumbers(unittest.TestCase):
    def _slice(self, blocked, depth=1.0):
        blocked = np.asarray(blocked, bool)
        zmin = np.where(np.ones_like(blocked), 0.0, np.inf)
        zmax = np.full(blocked.shape, depth)
        return foliage_mesh.slice_numbers(blocked, zmin, zmax, px=0.01)

    def test_a_hole_through_the_middle_does_not_get_the_slab_k(self):
        # 2 m wide, the outer quarters solid, the middle half clear: cover 0.5
        cols = np.r_[np.ones(50), np.zeros(100), np.ones(50)].astype(bool)
        s = self._slice(np.tile(cols, (25, 1)))
        self.assertAlmostEqual(s["cover"], 0.5, places=3)
        slab = -math.log(1 - 0.5) / 2.0
        self.assertAlmostEqual(s["k"], slab, places=4)            # kept as the slab value for the field map
        self.assertGreater(abs(s["k_disc"] - slab) / slab, 0.2)   # the light-grid k is not the slab one
        # and k_disc lets a disc as wide as the slice pass what the slice passes
        T = 1 - cols.astype(float)
        b = (np.arange(len(T)) + 0.5) / len(T) * 2 - 1
        L = 2 * 1.0 * np.sqrt(1 - b * b)
        self.assertAlmostEqual(float(np.exp(-s["k_disc"] * L).mean()), float(T.mean()), places=3)

    def test_uniform_slice(self):
        rng = np.random.default_rng(0)
        b = rng.random((25, 200)) < 0.4
        b[:, 0] = b[:, -1] = True
        s = self._slice(b)
        self.assertAlmostEqual(s["cover"], b.mean(), places=6)
        self.assertGreater(s["k_disc"], 0)
        self.assertGreater(s["k_chord"], 0)
        self.assertGreaterEqual(s["k90"], s["k_chord"] * 0.5)

    def test_empty_slice(self):
        self.assertIsNone(self._slice(np.zeros((25, 50), bool)))


class KindProfiles(unittest.TestCase):
    def _profile(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "foliage_shots.csv")
            with open(path, "w", newline="", encoding="utf8") as f:
                w = csv.writer(f)
                w.writerow(["id", "prefab", "kind", "band", "slice_m", "cover", "k", "width_m", "pixels"])
                w.writerows(rows)
            return bake_plants.kind_profiles(path, ["P"])[0]

    def test_k_keeps_the_blocked_cross_section_not_the_slab_formula(self):
        # 10 m tall, cover 0.5 over 2 m everywhere: 1 m of blocking per metre of height spread over a disc of radius 1
        rows = []
        for j in range(40):
            rows.append(["a", "P", "tree", "near", j * 0.25, 0.5, 9.0, 2.0, 300])   # the stored k is not read
            rows.append(["a", "P", "tree", 25, j * 0.25, 0.9, 9.0, 2.0, 1])          # a far band: ignored
        p = self._profile(rows)
        self.assertAlmostEqual(p["h"], 10.0, places=2)
        self.assertEqual(p["hw"], [1.0] * 10)
        for k in p["k"]:
            self.assertAlmostEqual(k, 1.0 / math.pi, places=4)   # 0.318, not the slab 0.3466

    def test_a_crown_with_a_hole_is_thinner_than_a_solid_one(self):
        solid = self._profile([["a", "P", "tree", "near", j * 0.25, 0.95, 1.5, 2.0, 1] for j in range(40)])
        holed = self._profile([["a", "P", "tree", "near", j * 0.25, 0.5, 1.5, 2.0, 1] for j in range(40)])
        self.assertAlmostEqual(solid["k"][5] / holed["k"][5], 0.95 / 0.5, places=3)


class Textures(unittest.TestCase):
    def test_bc4_block(self):
        # r0 = 200 > r1 = 100: palette 200, 100, then six steps; every texel uses index 1 (100) except the first (0)
        bits = 0
        for i in range(1, 16):
            bits |= 1 << (3 * i)
        block = bytes([200, 100]) + bits.to_bytes(6, "little")
        px = edds.bc4(block, 4, 4)
        self.assertEqual(px[0, 0], 200)
        self.assertTrue((px.ravel()[1:] == 100).all())
        # r0 <= r1: index 6 is 0 and 7 is 255
        block = bytes([10, 20]) + (6 | 7 << 3).to_bytes(6, "little")
        px = edds.bc4(block, 4, 4).ravel()
        self.assertEqual((px[0], px[1]), (0, 255))


@unittest.skipUnless(_game(), "Arma Reforger is not installed")
class GameFiles(unittest.TestCase):
    def test_spruce_mesh_and_opacity(self):
        lods, mats = foliage_mesh.mesh("Assets/Vegetation/Tree/Picea_Abies/t_picea_abies_3s.xob")
        self.assertEqual([l.triangles for l in lods], [9032, 3669, 994, 361, 4])
        crown = lods[0].parts[0]
        op, fade = foliage_mesh.material(crown.material)
        self.assertEqual(op, "Assets/Vegetation/_Polyplanes/polyplane_picea_abies_A.edds")
        self.assertEqual(fade, 0.3)
        self.assertTrue(-0.05 < crown.uv.min() and crown.uv.max() < 1.05)
        mips = foliage_mesh.opacity(op)
        self.assertEqual(mips[0].shape, (2048, 2048))
        self.assertGreater(mips[7].mean(), mips[0].mean() + 20)   # the denser small mips the game samples far away

    def test_prefab_material_swaps_are_used(self):
        # the autumn birch keeps the summer mesh and swaps its leaf material in the prefab (MaterialAssignClass)
        p = "Prefabs/Vegetation/Tree/t_betula_pendula/t_betula_pendula_2s_aut.et"
        lods, _ = foliage_mesh.mesh(foliage_mesh.prefab.resource(p, "Object"))
        crown = foliage_mesh._swapped(lods, foliage_mesh.material_swaps(p))[0].parts[0]
        self.assertEqual(foliage_mesh.material(crown.material)[0], "Assets/Vegetation/_Polyplanes/polyplane_betula_pendula_aut_A.edds")
        self.assertEqual(foliage_mesh.material(lods[0].parts[0].material)[0], "Assets/Vegetation/_Polyplanes/polyplane_betula_pendula_A.edds")

    def test_lod_rule_matches_the_measured_switches(self):
        # measured in the game (2026-10-05): spruce 3s swaps LOD0->1 between 60 and 70 m, LOD1->2 between 160 and 200 m
        lods, _ = foliage_mesh.mesh("Assets/Vegetation/Tree/Picea_Abies/t_picea_abies_3s.xob")
        sw = foliage_mesh.switch_distances(lods, foliage_mesh.lod_factors("Prefabs/Vegetation/Tree/t_picea_abies/t_picea_abies_3s.et"))
        self.assertTrue(45 < sw[0] < 80, sw)
        self.assertTrue(140 < sw[1] < 240, sw)


if __name__ == "__main__":
    unittest.main()
