"""Baker: a shaded-relief map in the style of BI's own 2D-map background, as web tiles, sharper than BI's.

BI's "Rasterization" export (the mapdata job's <World>.tga) is always 4096 x 4096 pixels, whatever the map's size:
1 m per pixel on Arland, about 3 m on Everon and Kolguyev, with no setting for more. This bake draws the same kind of
picture itself at 0.5 m per pixel from the line-of-sight tiles (los/: the ground at 1 m, and what stands on it at
0.5 m), with buildings, walls and rocks raised and trees and bushes left out, as BI's picture has them. The light
comes from the north-west, at several scales (hills, slopes, small bumps, edges), with weights fitted to BI's Arland
picture. The sea is BI's picture itself, stretched: it is smooth, and the line-of-sight tiles have no sea floor.

Same tile layout as the satellite tiles (rmtlib/satellite.py), relief/{z}/{x}/{y}.jpg, zoom 0 (0.39 m per pixel) up.
The whole-map picture is put together in a grey working file (relief.u8, beside the tiles' folder) and then cut.
"""

import glob
import gzip
import json
import os
import time

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, zoom

from .satellite import COARSE_Z, FINE_Z, OFFSET, TILE_PX, build_coarser, mpp, tile_range

Image.MAX_IMAGE_PIXELS = None

CELL = 0.5          # metres per pixel of the working picture
COARSE = 2.0        # metres per pixel of the whole-map ground used for the broad shading
HALO = 16           # pixels of the neighbouring chunks read round each chunk (for the fine shading)
RAISED = (1, 2)     # object kinds drawn: building, solid (walls, rocks); not trees, fences or bushes# Shading weights per blur scale in metres: (scale, weight of west-facing, weight of north-facing). Fitted to BI's
# Arland picture; a slope of 1 (45 degrees) facing the light brightens by the weight.
FINE = ((0, 0.15, 0.15), (2, 0.10, 0.12))
BROAD = ((8, 0.04, 0.05), (32, 0.14, 0.17), (128, 0.08, 0.12))
BASE = 0.80
HEIGHT = 0.0008     # brighter with height, per metre above HEIGHT_MID
HEIGHT_MID = 60.0
LOW, HIGH = 0.55, 1.0


def picture(raw):
    """BI's raster from the mapdata job (used for the sea), or None when that job hasn't run."""
    found = sorted(glob.glob(os.path.join(raw, 'mapdata', '*.tga')))
    return found[0] if found else None


class Los:
    def __init__(self, los_dir):
        with open(os.path.join(los_dir, 'index.json'), encoding='utf8') as f:
            ix = json.load(f)
        self.dir = los_dir
        g, t, s = ix['grid'], ix['terrain'], ix['surface']
        self.x0, self.z0, self.tile = float(g['x0']), float(g['z0']), float(g['tile'])
        self.cols, self.rows = int(g['cols']), int(g['rows'])
        self.T, self.t_unit = int(t['n']), float(t['unit'])
        self.S, self.q = int(s['n']), float(s['unit'])
        assert abs(self.tile / self.S - CELL) < 1e-6, 'relief expects 0.5 m surface cells'
        self.names = set(ix['tiles'])
        self.cache = {}

    def get(self, tx, tz):
        """(ground 1 m, raised height above ground 0.5 m) for a chunk, rows south to north; None for open sea."""
        key = (tx, tz)
        if key not in self.cache:
            if len(self.cache) > 12:
                self.cache.pop(next(iter(self.cache)))
            name = f'{tx}_{tz}'
            if name not in self.names:
                self.cache[key] = None
            else:
                with open(os.path.join(self.dir, name + '.bin.gz'), 'rb') as f:
                    raw = gzip.decompress(f.read())
                T, S = self.T, self.S
                o = T * T * 2
                ter = np.frombuffer(raw, '<u2', T * T).reshape(T, T).astype(np.float32) * self.t_unit
                top = np.frombuffer(raw, np.uint8, S * S, o).reshape(S, S).astype(np.float32) * self.q
                kind = np.frombuffer(raw, np.uint8, S * S, o + 2 * S * S).reshape(S, S)
                self.cache[key] = (ter, np.where(np.isin(kind, RAISED), top, 0).astype(np.float32))
        return self.cache[key]


def ground_fine(ter):
    """1 m ground (T x T, sharing its edge samples) to the 0.5 m cell centres (S x S), bilinear."""
    S = (ter.shape[0] - 1) * 2
    i = (np.arange(S) + 0.5) / 2
    c = np.minimum(i.astype(np.int64), ter.shape[0] - 2)
    f = (i - c).astype(np.float32)
    rows = ter[c] * (1 - f)[:, None] + ter[c + 1] * f[:, None]
    return rows[:, c] * (1 - f)[None, :] + rows[:, c + 1] * f[None, :]


def shade(h, spacing, scales):
    """Sum of directional shading terms of the height grid h (rows south to north) at the given blur scales."""
    out = np.zeros(h.shape, np.float32)
    for sigma, w_west, w_north in scales:
        hs = gaussian_filter(h, sigma / spacing) if sigma else h
        dz, dx = np.gradient(hs, spacing)   # dz: rise to the north, dx: rise to the east
        out += w_west * dx - w_north * dz   # rising to the east faces west; rising to the south faces north
    return out


def build(los_dir, tga, world, out_dir, log=print):
    """Draw the picture and cut the tile pyramid. Returns the zoom-0 tile count."""
    t0 = time.time()
    los = Los(los_dir)
    # the chunk grid can run past the world's edge (26 x 500 m on a 12.8 km map): draw all of it
    ext = max(world, los.cols * los.tile, los.rows * los.tile)
    n = int(round(ext / CELL))
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(os.path.dirname(os.path.abspath(out_dir)), 'relief.u8')
    grey = np.lib.format.open_memmap(work, mode='w+', dtype=np.uint8, shape=(n, n))   # rows south to north, 0 = sea

    # broad shading from the whole map's ground at 2 m
    m = int(round(ext / COARSE))
    ground = np.zeros((m, m), np.float32)
    step = int(round(COARSE / (los.tile / (los.T - 1))))
    per = int(round(los.tile / COARSE))
    for tz in range(los.rows):
        for tx in range(los.cols):
            t = los.get(tx, tz)
            if t is not None:
                ground[tz * per:(tz + 1) * per, tx * per:(tx + 1) * per] = t[0][:-1:step, :-1:step][:per, :per]
    broad = shade(ground, COARSE, BROAD) + HEIGHT * (gaussian_filter(ground, 16) - HEIGHT_MID)
    log(f'relief: broad shading ({time.time() - t0:.0f} s)')

    S = los.S
    made = 0
    for tz in range(los.rows):
        for tx in range(los.cols):
            if los.get(tx, tz) is None:
                continue
            # this chunk with a halo from its neighbours (open sea neighbours: height 0)
            big = np.zeros((S + 2 * HALO, S + 2 * HALO), np.float32)
            land = np.zeros_like(big, bool)
            for dz in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    t = los.get(tx + dx, tz + dz)
                    if t is None:
                        continue
                    h = ground_fine(t[0])
                    lnd = (h > 0) | (t[1] > 0)
                    h = h + t[1]
                    r0, c0 = HALO + dz * S, HALO + dx * S
                    rs, cs = slice(max(r0, 0), min(r0 + S, big.shape[0])), slice(max(c0, 0), min(c0 + S, big.shape[1]))
                    big[rs, cs] = h[rs.start - r0:rs.stop - r0, cs.start - c0:cs.stop - c0]
                    land[rs, cs] = lnd[rs.start - r0:rs.stop - r0, cs.start - c0:cs.stop - c0]
            fine = shade(big, CELL, FINE)[HALO:-HALO, HALO:-HALO]
            # the broad shading for this chunk, from 2 m to 0.5 m
            k = int(COARSE / CELL)
            b = broad[tz * per:(tz + 1) * per, tx * per:(tx + 1) * per]
            b = zoom(b, k, order=1, mode='nearest')[:S, :S]
            v = np.clip(BASE + fine + b, LOW, HIGH)
            g = np.clip(np.round(v * 255), 1, 255).astype(np.uint8)
            g[~land[HALO:-HALO, HALO:-HALO]] = 0
            grey[tz * S:(tz + 1) * S, tx * S:(tx + 1) * S] = g
            made += 1
    grey.flush()
    log(f'relief: {made} chunks drawn at {CELL} m ({time.time() - t0:.0f} s)')

    # tiles: the grey picture north up, the sea from BI's picture
    land_img = Image.fromarray(np.ascontiguousarray(grey[::-1]), 'L')
    bi = Image.open(tga).convert('RGB')
    bpx = bi.size[0] / world
    span = TILE_PX * mpp(FINE_Z)
    xs, ys = tile_range(FINE_Z, 0, 0, world, world)
    tiles = 0
    for ty in ys:
        for tx in xs:
            x0 = tx * span - OFFSET
            z1 = (ty + 1) * span - OFFSET
            box = lambda s, edge: (x0 * s, (edge - z1) * s, (x0 + span) * s, (edge - z1 + span) * s)
            sea = bi.transform((TILE_PX, TILE_PX), Image.Transform.EXTENT, box(bpx, world), Image.Resampling.BILINEAR,
                               fillcolor=bi.getpixel((0, 0)))
            g = land_img.transform((TILE_PX, TILE_PX), Image.Transform.EXTENT, box(1 / CELL, ext),
                                   Image.Resampling.BILINEAR, fillcolor=0)
            mask = land_img.transform((TILE_PX, TILE_PX), Image.Transform.EXTENT, box(1 / CELL, ext),
                                      Image.Resampling.NEAREST, fillcolor=0).point(lambda p: 255 if p else 0)
            tile = Image.composite(Image.merge('RGB', (g, g, g)), sea, mask)
            folder = os.path.join(out_dir, str(FINE_Z), str(tx))
            os.makedirs(folder, exist_ok=True)
            tile.save(os.path.join(folder, f'{ty}.jpg'), 'JPEG', quality=85)
            tiles += 1
    log(f'relief: zoom {FINE_Z}: {tiles} tiles ({time.time() - t0:.0f} s)')
    for url_z in range(FINE_Z + 1, COARSE_Z + 1):
        log(f'relief: zoom {url_z}: {build_coarser(out_dir, url_z)} tiles')
    del grey, land_img
    try:
        os.remove(work)
    except OSError:
        log(f'relief: could not remove the working file {work}')
    return tiles
