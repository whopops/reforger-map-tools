"""Build the field map's own satellite tiles. No external tile server.

The map asks for tiles/{z}/{x}/{y}.jpg. z 0 is the finest (128 tiles a side,
100 m each); z 5 is the coarsest (4 tiles). Coordinates match the map:
50 m origin offset, scale 12.501, 256 px tiles, north at the top of each picture.

Two sources, either is enough:

  python py/make_tiles.py --image everon.png --out tiles --size 12800
      one north-up picture of the whole island, west at the left, covering
      world x = 0..size and z = 0..size

  python py/make_tiles.py --shots <export>/satellite --out tiles
      screenshots from -job=satellite. Each s_TX_TZ.txt names the ground square.
      The center square of the screenshot is that ground square (set the editor
      camera to the fov and height the plugin prints).

Copy the result into the map's tile_cache/ and it will serve these pictures
instead of fetching them.
"""

import argparse
import csv
import os
import sys
from PIL import Image

SCALE = 12.501
OFFSET = 50.0
TILE_PX = 256
FINE_Z = 0
COARSE_Z = 5
SEA = (26, 36, 32)


def tile_count(url_z):
    return 2 ** (7 - url_z)


def world_to_pixel(url_z, tx, ty, x, z):
    """Pixel position inside a tile for a world point. (0, 0) is the top-left."""
    zoom = 5 - url_z
    metres_per_px = SCALE / (2 ** zoom)
    px = (x + OFFSET) / metres_per_px - tx * TILE_PX
    c_y = -ty - 1
    py = -(z + OFFSET) / metres_per_px - c_y * TILE_PX
    return px, py


def pixel_world(url_z, tx, ty, px, py):
    """World x, z at a pixel corner inside the tile. px, py are edges, not centers."""
    zoom = 5 - url_z
    metres_per_px = SCALE / (2 ** zoom)
    x = (tx * TILE_PX + px) * metres_per_px - OFFSET
    c_y = -ty - 1
    z = -(c_y * TILE_PX + py) * metres_per_px - OFFSET
    return x, z


def parse_only(text):
    if not text:
        return None
    z, x, y = text.split("/")
    return int(z), int(x), int(y)


def sample_image(image, size, x, z):
    w, h = image.size
    if x < 0 or z < 0 or x > size or z > size:
        return SEA
    u = 0 if w == 1 else x / size * (w - 1)
    v = 0 if h == 1 else (size - z) / size * (h - 1)
    return image.getpixel((min(w - 1, max(0, int(round(u)))), min(h - 1, max(0, int(round(v))))))


def render_tile_from_image(image, size, url_z, tx, ty):
    out = Image.new("RGB", (TILE_PX, TILE_PX), SEA)
    pix = out.load()
    for j in range(TILE_PX):
        for i in range(TILE_PX):
            x, z = pixel_world(url_z, tx, ty, i + 0.5, j + 0.5)
            pix[i, j] = sample_image(image, size, x, z)
    return out


def save_tile(out_dir, url_z, tx, ty, image):
    folder = os.path.join(out_dir, str(url_z), str(tx))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{ty}.jpg")
    image.save(path, "JPEG", quality=85)
    return path


def iter_tiles(url_z, only):
    if only and only[0] == url_z:
        yield only[1], only[2]
        return
    if only:
        return
    n = tile_count(url_z)
    for ty in range(n):
        for tx in range(n):
            yield tx, ty


def build_from_image(image_path, out_dir, size, only):
    image = Image.open(image_path).convert("RGB")
    made = 0
    for tx, ty in iter_tiles(FINE_Z, only):
        save_tile(out_dir, FINE_Z, tx, ty, render_tile_from_image(image, size, FINE_Z, tx, ty))
        made += 1
    if only:
        return made
    for url_z in range(FINE_Z + 1, COARSE_Z + 1):
        made += build_coarser(out_dir, url_z)
    return made


def build_coarser(out_dir, url_z):
    n = tile_count(url_z)
    made = 0
    for ty in range(n):
        for tx in range(n):
            canvas = Image.new("RGB", (TILE_PX * 2, TILE_PX * 2), SEA)
            # Higher y is north, which is the top of the picture.
            places = (
                (0, 0, tx * 2, ty * 2 + 1),
                (TILE_PX, 0, tx * 2 + 1, ty * 2 + 1),
                (0, TILE_PX, tx * 2, ty * 2),
                (TILE_PX, TILE_PX, tx * 2 + 1, ty * 2),
            )
            for left, top, fx, fy in places:
                path = os.path.join(out_dir, str(url_z - 1), str(fx), f"{fy}.jpg")
                if os.path.isfile(path):
                    canvas.paste(Image.open(path).convert("RGB"), (left, top))
            save_tile(out_dir, url_z, tx, ty, canvas.resize((TILE_PX, TILE_PX), Image.Resampling.BOX))
            made += 1
    return made


def load_shots(folder, png_dir=None):
    shots = []
    search_dirs = [folder]
    if png_dir and os.path.abspath(png_dir) != os.path.abspath(folder):
        search_dirs.append(png_dir)
    for fn in sorted(os.listdir(folder)):
        if not (fn.startswith("s_") and fn.endswith(".txt")):
            continue
        if not os.path.isfile(os.path.join(folder, fn + ".ok")):
            continue
        with open(os.path.join(folder, fn), encoding="utf8", newline="") as f:
            rows = list(csv.DictReader(f))
        if len(rows) != 1:
            raise SystemExit(f"{fn} should be one shot")
        row = rows[0]
        stem = os.path.splitext(fn)[0]
        image = None
        names = [stem]
        if row.get("file") and row["file"] not in names:
            names.append(row["file"])
        for directory in search_dirs:
            for name in names:
                for ext in (".png", ".jpg", ".jpeg"):
                    candidate = os.path.join(directory, name + ext)
                    if os.path.isfile(candidate):
                        image = candidate
                        break
                if image:
                    break
            if image:
                break
        if image is None:
            raise SystemExit(f"no picture for {fn} (looked for {stem}.png)")
        shots.append({
            "image": image,
            "x0": float(row["x0"]),
            "z0": float(row["z0"]),
            "x1": float(row["x1"]),
            "z1": float(row["z1"]),
        })
    if not shots:
        raise SystemExit(f"no finished shots in {folder}")
    return shots


def center_square(image):
    w, h = image.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return image.crop((left, top, left + side, top + side))


def paste_shot(tile, shot_image, shot, url_z, tx, ty):
    """Paste the shot's ground square into the overlapping part of this tile."""
    x0, z0, x1, z1 = shot["x0"], shot["z0"], shot["x1"], shot["z1"]
    corners = (
        pixel_world(url_z, tx, ty, 0, 0),
        pixel_world(url_z, tx, ty, TILE_PX, TILE_PX),
    )
    tile_x0, tile_x1 = sorted(c[0] for c in corners)
    tile_z0, tile_z1 = sorted(c[1] for c in corners)
    ix0, ix1 = max(tile_x0, x0), min(tile_x1, x1)
    iz0, iz1 = max(tile_z0, z0), min(tile_z1, z1)
    if ix1 <= ix0 or iz1 <= iz0:
        return
    dest = (
        world_to_pixel(url_z, tx, ty, ix0, iz1),
        world_to_pixel(url_z, tx, ty, ix1, iz0),
    )
    left = int(round(min(dest[0][0], dest[1][0])))
    right = int(round(max(dest[0][0], dest[1][0])))
    top = int(round(min(dest[0][1], dest[1][1])))
    bottom = int(round(max(dest[0][1], dest[1][1])))
    left = max(0, min(TILE_PX, left))
    right = max(0, min(TILE_PX, right))
    top = max(0, min(TILE_PX, top))
    bottom = max(0, min(TILE_PX, bottom))
    if right <= left or bottom <= top:
        return
    crop = center_square(shot_image)
    cw, ch = crop.size
    sx0 = (ix0 - x0) / (x1 - x0) * cw
    sx1 = (ix1 - x0) / (x1 - x0) * cw
    sy0 = (z1 - iz1) / (z1 - z0) * ch
    sy1 = (z1 - iz0) / (z1 - z0) * ch
    patch = crop.resize((max(1, right - left), max(1, bottom - top)), Image.Resampling.BOX,
                         box=(sx0, sy0, sx1, sy1))
    tile.paste(patch, (left, top))


def build_from_shots(folder, out_dir, only, png_dir=None):
    shots = load_shots(folder, png_dir)
    opened = [(center_square(Image.open(s["image"]).convert("RGB")), s) for s in shots]
    made = 0
    for tx, ty in iter_tiles(FINE_Z, only):
        tile = Image.new("RGB", (TILE_PX, TILE_PX), SEA)
        for image, shot in opened:
            paste_shot(tile, image, shot, FINE_Z, tx, ty)
        save_tile(out_dir, FINE_Z, tx, ty, tile)
        made += 1
    if only:
        return made
    for url_z in range(FINE_Z + 1, COARSE_Z + 1):
        made += build_coarser(out_dir, url_z)
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write the map's satellite tile pyramid.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--image", help="north-up picture of the whole island")
    ap.add_argument("--shots", help="folder of s_TX_TZ.txt shots from -job=satellite")
    ap.add_argument("--size", type=float, default=12800.0, help="world metres covered by --image")
    ap.add_argument("--png-dir", help="folder of s_TX_TZ pictures if they are not beside the txt")
    ap.add_argument("--only", help="one tile z/x/y, for a check; skips the rest of the pyramid")
    args = ap.parse_args(argv)
    if bool(args.image) == bool(args.shots):
        raise SystemExit("pass exactly one of --image or --shots")
    only = parse_only(args.only)
    if args.image:
        made = build_from_image(args.image, args.out, args.size, only)
    else:
        made = build_from_shots(args.shots, args.out, only, args.png_dir)
    print(f"wrote {made} tiles to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
