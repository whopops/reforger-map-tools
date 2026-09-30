"""Our own satellite tiles: correct the game's top-down shots to a true map and cut the tile pyramid.

The shots (satellite job, taken in the game) are perspective pictures from straight above with a narrow lens,
one per ground square, camera settings in s_<c>_<r>.txt. Every camera parameter is known, so a ground point
(x, z) at terrain height h appears in a shot at
    u = W/2 + f (x - cx) / (H - h)        v = Hh/2 - f (z - cz) / (H - h)       f = (Hh / 2) / tan(fov / 2)
(north up, east right). For each map pixel we take the terrain height from the terrain export, use the shot whose
centre is nearest (the least lean for tall objects), and sample it there. That removes the scale changes hills
cause; trees and buildings lean a little away from each shot's centre, less the narrower the lens.

Tiles follow the field map's layout, tiles/{z}/{x}/{y}.jpg: 256 px, zoom 0 the finest at 12.501/32 m per pixel
(about 0.39 m), each zoom up halves the detail, a 50 m origin offset, y counted from the south.
"""

import glob
import math
import os
import re
import time
from functools import lru_cache

import numpy as np
from PIL import Image

SCALE = 12.501      # metres per pixel at the coarsest zoom 5 (the EnfusionMapMaker / field-map convention)
OFFSET = 50.0
TILE_PX = 256
FINE_Z = 0
COARSE_Z = 5
SEA = (26, 36, 32)


def mpp(url_z):
    return SCALE / 2 ** (COARSE_Z - url_z)


class Terrain:
    """Ground height anywhere, from the terrain job's chunks (loaded on demand)."""

    def __init__(self, raw):
        self.folder = os.path.join(raw, 'terrain')
        self.index = {}
        for fn in os.listdir(self.folder):
            m = re.match(r't_(\d+)_(\d+)\.csv$', fn)
            if m:
                with open(os.path.join(self.folder, fn), encoding='utf8') as f:
                    x0, z0, step, cols, rows = f.readline().strip().split(',')
                self.index[(int(m.group(1)), int(m.group(2)))] = (float(x0), float(z0), float(step), int(cols), int(rows))
        if not self.index:
            raise SystemExit(f'no terrain chunks in {self.folder}')
        any_chunk = next(iter(self.index.values()))
        self.step = any_chunk[2]
        self.tile = (any_chunk[3] - 1) * self.step
        self.gx0 = min(v[0] for v in self.index.values())
        self.gz0 = min(v[1] for v in self.index.values())

    @lru_cache(maxsize=16)
    def chunk(self, tx, tz):
        meta = self.index.get((tx, tz))
        if not meta:
            return None
        with open(os.path.join(self.folder, f't_{tx}_{tz}.csv'), encoding='utf8') as f:
            f.readline()
            a = np.array(f.read().replace('\n', ',').strip(',').split(','), dtype=np.float32)
        return a.reshape(meta[4], meta[3]) / 100.0

    def heights(self, x, z):
        """Bilinear terrain height (m) for arrays of x, z; 0 (sea level) outside the export."""
        out = np.zeros(x.shape, np.float32)
        tx = np.floor((x - self.gx0) / self.tile).astype(np.int64)
        tz = np.floor((z - self.gz0) / self.tile).astype(np.int64)
        for key in set(zip(tx.ravel().tolist(), tz.ravel().tolist())):
            grid = self.chunk(*key)
            if grid is None:
                continue
            sel = (tx == key[0]) & (tz == key[1])
            lx = (x[sel] - (self.gx0 + key[0] * self.tile)) / self.step
            lz = (z[sel] - (self.gz0 + key[1] * self.tile)) / self.step
            n = grid.shape[0] - 1
            c0 = np.clip(np.floor(lx).astype(np.int64), 0, n - 1)
            r0 = np.clip(np.floor(lz).astype(np.int64), 0, n - 1)
            fx = np.clip(lx - c0, 0, 1)
            fz = np.clip(lz - r0, 0, 1)
            out[sel] = (grid[r0, c0] * (1 - fx) * (1 - fz) + grid[r0, c0 + 1] * fx * (1 - fz)
                        + grid[r0 + 1, c0] * (1 - fx) * fz + grid[r0 + 1, c0 + 1] * fx * fz)
        return out


class Shots:
    """The captured shots and their cameras."""

    def __init__(self, folder):
        self.folder = folder
        self.cams = {}
        for txt in glob.glob(os.path.join(folder, 's_*_*.txt')):
            m = re.search(r's_(\d+)_(\d+)\.txt$', txt)
            with open(txt, encoding='utf8') as f:
                f.readline()
                x, z, span, height, fov, mode = f.readline().strip().split(',')[:6]
            img = self._image_path(txt[:-4])
            if img:
                self.cams[(int(m.group(1)), int(m.group(2)))] = dict(
                    x=float(x), z=float(z), span=float(span), H=float(height), fov=float(fov), img=img)
        if not self.cams:
            raise SystemExit(f'no finished shots in {folder}')
        xs = sorted({c['x'] for c in self.cams.values()})
        zs = sorted({c['z'] for c in self.cams.values()})
        self.step = next(iter(self.cams.values()))['span']
        # grid origin: the corner of shot (0, 0)'s square
        c00 = min(self.cams)
        cam = self.cams[c00]
        self.gx0 = cam['x'] - self.step / 2 - c00[0] * self.step
        self.gz0 = cam['z'] - self.step / 2 - c00[1] * self.step

    @staticmethod
    def _image_path(stem):
        for ext in ('.bmp', '.bmp.png', '.png', '.jpg'):
            if os.path.isfile(stem + ext):
                return stem + ext
        return None

    @lru_cache(maxsize=24)
    def pixels(self, key):
        return np.asarray(Image.open(self.cams[key]['img']).convert('RGB'), dtype=np.float32)

    def bounds(self):
        cs = [k[0] for k in self.cams]
        rs = [k[1] for k in self.cams]
        return (self.gx0 + min(cs) * self.step, self.gz0 + min(rs) * self.step,
                self.gx0 + (max(cs) + 1) * self.step, self.gz0 + (max(rs) + 1) * self.step)


def sample(img, u, v):
    """Bilinear sample of an HxWx3 image at float pixel coordinates; NaN where outside."""
    h, w = img.shape[:2]
    ok = (u >= 0) & (v >= 0) & (u <= w - 1) & (v <= h - 1)
    u = np.clip(u, 0, w - 1.001)
    v = np.clip(v, 0, h - 1.001)
    u0 = np.floor(u).astype(np.int64)
    v0 = np.floor(v).astype(np.int64)
    fu = (u - u0)[..., None]
    fv = (v - v0)[..., None]
    out = (img[v0, u0] * (1 - fu) * (1 - fv) + img[v0, u0 + 1] * fu * (1 - fv)
           + img[v0 + 1, u0] * (1 - fu) * fv + img[v0 + 1, u0 + 1] * fu * fv)
    out[~ok] = np.nan
    return out


def render(shots, terrain, x, z):
    """Colours for arrays of ground points (x, z): each from the nearest shot, corrected for terrain height."""
    h = terrain.heights(x, z)
    col = np.floor((x - shots.gx0) / shots.step).astype(np.int64)
    row = np.floor((z - shots.gz0) / shots.step).astype(np.int64)
    out = np.full(x.shape + (3,), np.nan, np.float32)
    for key in set(zip(col.ravel().tolist(), row.ravel().tolist())):
        cam = shots.cams.get(key)
        if not cam:
            continue
        sel = (col == key[0]) & (row == key[1])
        img = shots.pixels(key)
        ih, iw = img.shape[:2]
        f = (ih / 2) / math.tan(math.radians(cam['fov'] / 2))
        depth = cam['H'] - h[sel]
        u = iw / 2 + f * (x[sel] - cam['x']) / depth
        v = ih / 2 - f * (z[sel] - cam['z']) / depth
        out[sel] = sample(img, u, v)
    return out


def tile_world(url_z, tx, ty):
    """World x, z of every pixel centre of a tile (256 x 256), row 0 at the top (north)."""
    m = mpp(url_z)
    i = np.arange(TILE_PX) + 0.5
    x = (tx * TILE_PX + i) * m - OFFSET
    z = ((ty + 1) * TILE_PX - i) * m - OFFSET
    return np.meshgrid(x, z)


def tile_range(url_z, x0, z0, x1, z1):
    """Tile columns / rows (url y counts from the south) covering a world box."""
    span = TILE_PX * mpp(url_z)
    return (range(int((x0 + OFFSET) // span), int(math.ceil((x1 + OFFSET) / span))),
            range(int((z0 + OFFSET) // span), int(math.ceil((z1 + OFFSET) / span))))


def save(out_dir, url_z, tx, ty, rgb):
    folder = os.path.join(out_dir, str(url_z), str(tx))
    os.makedirs(folder, exist_ok=True)
    Image.fromarray(rgb).save(os.path.join(folder, f'{ty}.jpg'), 'JPEG', quality=85)


def build(shots_dir, terrain_raw, out_dir, log=print, only_box=None):
    """Write the tile pyramid. only_box = (x0, z0, x1, z1) limits zoom 0 to part of the map (tests)."""
    t0 = time.time()
    shots = Shots(shots_dir)
    terrain = Terrain(terrain_raw)
    box = only_box or shots.bounds()
    xs, ys = tile_range(FINE_Z, *box)
    made = 0
    for ty in ys:
        for tx in xs:
            x, z = tile_world(FINE_Z, tx, ty)
            rgb = render(shots, terrain, x, z)
            if np.isnan(rgb).all():
                continue
            rgb = np.where(np.isnan(rgb), np.array(SEA, np.float32), rgb)
            save(out_dir, FINE_Z, tx, ty, np.clip(np.round(rgb), 0, 255).astype(np.uint8))
            made += 1
    log(f'satellite: zoom {FINE_Z}: {made} tiles ({time.time() - t0:.0f} s)')
    for url_z in range(FINE_Z + 1, COARSE_Z + 1):
        n = build_coarser(out_dir, url_z)
        log(f'satellite: zoom {url_z}: {n} tiles')
    return made


def build_coarser(out_dir, url_z):
    """Each tile from the four below it (y counts from the south, so the higher y is the top half)."""
    below = os.path.join(out_dir, str(url_z - 1))
    if not os.path.isdir(below):
        return 0
    parents = set()
    for xdir in os.listdir(below):
        for fn in os.listdir(os.path.join(below, xdir)):
            parents.add((int(xdir) // 2, int(fn[:-4]) // 2))
    for tx, ty in parents:
        canvas = Image.new('RGB', (TILE_PX * 2, TILE_PX * 2), SEA)
        for left, top, fx, fy in ((0, 0, 2 * tx, 2 * ty + 1), (TILE_PX, 0, 2 * tx + 1, 2 * ty + 1),
                                  (0, TILE_PX, 2 * tx, 2 * ty), (TILE_PX, TILE_PX, 2 * tx + 1, 2 * ty)):
            path = os.path.join(below, str(fx), f'{fy}.jpg')
            if os.path.isfile(path):
                canvas.paste(Image.open(path).convert('RGB'), (left, top))
        folder = os.path.join(out_dir, str(url_z), str(tx))
        os.makedirs(folder, exist_ok=True)
        canvas.resize((TILE_PX, TILE_PX), Image.Resampling.BOX).save(os.path.join(folder, f'{ty}.jpg'), 'JPEG', quality=85)
    return len(parents)


def mosaic(shots_dir, terrain_raw, box, metres_per_px=1.0):
    """One north-up picture of a world box (for checking alignment)."""
    shots = Shots(shots_dir)
    terrain = Terrain(terrain_raw)
    x0, z0, x1, z1 = box
    xs = np.arange(x0, x1, metres_per_px) + metres_per_px / 2
    zs = np.arange(z1, z0, -metres_per_px) - metres_per_px / 2
    x, z = np.meshgrid(xs, zs)
    rgb = render(shots, terrain, x, z)
    rgb = np.where(np.isnan(rgb), np.array(SEA, np.float32), rgb)
    return Image.fromarray(np.clip(np.round(rgb), 0, 255).astype(np.uint8))
