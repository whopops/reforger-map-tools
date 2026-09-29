import os
import tempfile
import unittest

from PIL import Image

import make_tiles


class TileTests(unittest.TestCase):
    def test_center_of_the_island_lands_in_the_middle_tile(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "island.png")
            out = os.path.join(tmp, "tiles")
            image = Image.new("RGB", (4096, 4096), (0, 40, 0))
            pix = image.load()
            # One source pixel is about 3 m, and the middle tile is about 100 m across.
            u = int(round(6400 / 12800 * 4095))
            v = int(round((12800 - 6400) / 12800 * 4095))
            for du in range(-2, 3):
                for dv in range(-2, 3):
                    pix[u + du, v + dv] = (220, 20, 20)
            image.save(image_path)
            make_tiles.main(["--image", image_path, "--out", out, "--size", "12800", "--only", "0/64/64"])
            tile = Image.open(os.path.join(out, "0", "64", "64.jpg")).convert("RGB")
            self.assertGreater(tile.getpixel((128, 128))[0], 150)
            self.assertLess(tile.getpixel((8, 248))[0], 40)

    def test_shot_fills_its_ground_square(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = os.path.join(tmp, "satellite")
            os.makedirs(shots)
            x0, z_top = make_tiles.pixel_world(0, 64, 64, 0, 0)
            x1, z_bot = make_tiles.pixel_world(0, 64, 64, 256, 256)
            west, east = sorted((x0, x1))
            south, north = sorted((z_top, z_bot))
            with open(os.path.join(shots, "s_0_0.txt"), "w", encoding="utf8") as f:
                f.write("x0,z0,x1,z1,camera,fov,file\n")
                f.write(f"{west},{south},{east},{north},1900,15,s_0_0\n")
            with open(os.path.join(shots, "s_0_0.txt.ok"), "w", encoding="utf8") as f:
                f.write("ok\n")
            Image.new("RGB", (64, 48), (10, 180, 220)).save(os.path.join(shots, "s_0_0.png"))
            out = os.path.join(tmp, "tiles")
            make_tiles.main(["--shots", shots, "--out", out, "--only", "0/64/64"])
            tile = Image.open(os.path.join(out, "0", "64", "64.jpg")).convert("RGB")
            pixel = tile.getpixel((128, 128))
            self.assertGreater(pixel[2], 150)
            self.assertLess(pixel[0], 80)

    def test_world_point_uses_the_leaflet_tile_index(self):
        import math
        x, z = 6400.0, 6400.0
        scale = 2 ** 5
        px = scale * (x + make_tiles.OFFSET) / make_tiles.SCALE
        py = scale * (-(z + make_tiles.OFFSET)) / make_tiles.SCALE
        tx = math.floor(px / make_tiles.TILE_PX)
        ty = -(math.floor(py / make_tiles.TILE_PX) + 1)
        self.assertEqual((tx, ty), (64, 64))
        cx, cz = make_tiles.pixel_world(0, tx, ty, 128, 128)
        self.assertAlmostEqual(cx, x, delta=1.0)
        self.assertAlmostEqual(cz, z, delta=1.0)

    def test_coarser_tile_keeps_north_at_the_top(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "tiles")
            red = Image.new("RGB", (256, 256), (200, 0, 0))
            green = Image.new("RGB", (256, 256), (0, 80, 0))
            make_tiles.save_tile(out, 0, 0, 1, red)
            make_tiles.save_tile(out, 0, 0, 0, green)
            make_tiles.build_coarser(out, 1)
            tile = Image.open(os.path.join(out, "1", "0", "0.jpg")).convert("RGB")
            self.assertGreater(tile.getpixel((32, 8))[0], 150)
            self.assertGreater(tile.getpixel((32, 248))[1], 40)
            self.assertLess(tile.getpixel((32, 248))[0], 40)

    def test_png_dir_is_used_when_the_shot_is_not_beside_the_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = os.path.join(tmp, "satellite")
            pngs = os.path.join(tmp, "screenshots")
            os.makedirs(shots)
            os.makedirs(pngs)
            x0, z_top = make_tiles.pixel_world(0, 64, 64, 0, 0)
            x1, z_bot = make_tiles.pixel_world(0, 64, 64, 256, 256)
            west, east = sorted((x0, x1))
            south, north = sorted((z_top, z_bot))
            with open(os.path.join(shots, "s_0_0.txt"), "w", encoding="utf8") as f:
                f.write("x0,z0,x1,z1,camera,fov,file\n")
                f.write(f"{west},{south},{east},{north},1900,15,s_0_0\n")
            with open(os.path.join(shots, "s_0_0.txt.ok"), "w", encoding="utf8") as f:
                f.write("ok\n")
            Image.new("RGB", (32, 24), (10, 180, 220)).save(os.path.join(pngs, "s_0_0.png"))
            out = os.path.join(tmp, "tiles")
            make_tiles.main(["--shots", shots, "--png-dir", pngs, "--out", out, "--only", "0/64/64"])
            tile = Image.open(os.path.join(out, "0", "64", "64.jpg")).convert("RGB")
            self.assertGreater(tile.getpixel((128, 128))[2], 150)


if __name__ == "__main__":
    unittest.main()
