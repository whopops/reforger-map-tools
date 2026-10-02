"""Line-of-sight tiles and the 10 m "light" grids, from the terrain, entities and surface jobs.

Port of arma-map's everon-map/tools/bake_los.py (proven on Everon; since removed from arma-map, see its git
history), made map-independent: the chunk grid, its origin,
the height unit and the light-grid size all come from the export's probe.json.

Output (site/los/):
  <tx>_<tz>.bin.gz per chunk, little endian:
    terrain  Uint16[T*T]   ground height in `terrain.unit` metres above the water line (sea floor clamped to 0)
    top      Uint8[S*S]    top of whatever stands on each surface cell, in 0.25 m above the ground
    bottom   Uint8[S*S]    where it starts (canopy underside; 0 for solid things), same units
    kind     Uint8[S*S]    0 nothing, 1 building, 2 solid, 3 tree, 4 see-through fence, 5 bush / low plant
    cover    Uint8[S*S]    top of what stops bullets, same units (0 = nothing)
  index.json   grid, units, layout and the list of chunks written (open sea is skipped)
Rows run south to north, columns west to east.

Light grids (site/light/, gzipped, cols*50 x rows*50 cells of 10 m, rows south to north):
  height.bin Int16 dm, forest.bin 1 bit, canopy.bin Uint8 x 4 planes (top, base, low, crown),
  buildings.bin Uint8 m, lz.bin Uint8 (0 water, 1 good, 2 marginal, 3 no-go)
"""

import csv
import gzip
import json
import math
import os
import re
import time
import warnings
from functools import lru_cache

import numpy as np

Q = 0.25            # height unit for top / bottom / cover (metres)
LIGHT_CELL = 10     # metres

# Wall and fence families (the folder after Prefabs/Structures/Walls/), sorted by whether they block sight.
SOLID = re.compile(r'/Walls/(Stone|Brick|Concrete|Metal|HouseRuins|Cultural|BuildingParts/Industrial)/|/Walls/Wooden/WoodenWall_')
SEE_THROUGH = re.compile(r'/Walls/(Pole|Net|Pipe|Cemeteries)/|/Walls/Wooden/(WoodenRural_|WoodenFenceOld_)|/Walls/BuildingParts/Doors/')


class Grid:
    """The export's chunk grid (from probe.json and the first terrain / surface headers)."""

    def __init__(self, raw, probe=None):
        p = probe
        if p is None:
            with open(os.path.join(raw, 'probe.json'), encoding='utf8') as f:
                p = json.load(f)
        self.raw = raw
        self.x0, self.z0 = float(p['min'][0]), float(p['min'][2])
        self.tile = float(p['tile'])
        self.cols, self.rows = int(p['cols']), int(p['rows'])
        self.max_y = float(p['max'][1])
        # terrain: centimetres if the highest ground fits in Uint16, else the smallest whole-cm step that does
        self.t_unit_cm = max(1, math.ceil(max(self.max_y, 0) * 100 / 65535))
        t = self._header('terrain', 't')
        s = self._header('surface', 's')
        self.t_n, self.t_step = int(t[3]), float(t[2])
        self.s_n, self.cell = int(s[3]), float(s[2])

    def _header(self, folder, prefix):
        for fn in os.listdir(os.path.join(self.raw, folder)):
            if fn.startswith(prefix + '_') and fn.endswith('.csv'):
                with open(os.path.join(self.raw, folder, fn), encoding='utf8') as f:
                    return f.readline().strip().split(',')
        raise SystemExit(f'no {folder} chunks in {self.raw}')

    def origin(self, tx, tz):
        return self.x0 + tx * self.tile, self.z0 + tz * self.tile

    def chunks(self):
        return [(tx, tz) for tz in range(self.rows) for tx in range(self.cols)]


def read_numbers(path):
    """A CSV of numbers (after its header line) as one flat float array."""
    with open(path, encoding='utf8') as f:
        head = f.readline()
        body = f.read()
    if not body.strip():
        return head, np.zeros(0)
    return head, np.array(body.replace('\n', ',').strip(',').split(','), dtype=np.float64)


def iter_objects(raw):
    folder = os.path.join(raw, 'objects')
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith('.csv'):
            continue
        with open(os.path.join(folder, fn), encoding='utf8', errors='replace', newline='') as f:
            yield from csv.DictReader(f)


def load_objects(raw):
    """Walls (kind, minx, minz, maxx, maxz, top y, yaw), tree crowns (x, z, r) and poles (x, z, top y)."""
    walls, trees, poles = [], [], []
    for r in iter_objects(raw):
        p = r['prefab']
        if '/Walls/' in p:
            kind = 1 if SOLID.search(p) else 2 if SEE_THROUGH.search(p) else 0
            if kind:
                walls.append((kind, float(r['minx']), float(r['minz']), float(r['maxx']), float(r['maxz']),
                              float(r['maxy']), float(r['yaw'])))
            continue
        wx, wz = float(r['maxx']) - float(r['minx']), float(r['maxz']) - float(r['minz'])
        h = float(r['maxy']) - float(r['miny'])
        if '/Vegetation/Tree/' in p:
            # the crown: the box's narrower side, as trees lean and the box includes the whole spread
            trees.append((float(r['x']), float(r['z']), max(min(wx, wz) / 2, 0.75)))
        elif '/Vegetation/' not in p and r['class'] not in ('RoadEntity', 'DecalEntity', 'LightEntity') \
                and h >= 3 and max(wx, wz) <= 1.5:
            poles.append((float(r['x']), float(r['z']), float(r['maxy'])))
    as_arr = lambda a, n: np.array(a, np.float64).reshape(-1, n)
    return as_arr(walls, 7), as_arr(trees, 3), as_arr(poles, 3)


def line_cells(seg, n_max):
    """Cells (x, z) a segment passes through, sampled every quarter cell, inside the chunk."""
    x0, z0, x1, z1 = seg
    n = int(max(abs(x1 - x0), abs(z1 - z0)) * 4) + 1
    t = np.linspace(0, 1, n)
    xs = np.floor(x0 + (x1 - x0) * t).astype(np.int64)
    zs = np.floor(z0 + (z1 - z0) * t).astype(np.int64)
    ok = (xs >= 0) & (xs < n_max) & (zs >= 0) & (zs < n_max)
    return xs[ok], zs[ok]


def wall_segment(w, kind, x0, z0, cell, n):
    """The wall's centre line in cell coordinates, from its box. A thin piece runs along the box's long side; a
    diagonal one runs along whichever diagonal the scan saw more of it on."""
    _, minx, minz, maxx, maxz, _, _ = w
    cx0, cz0 = (minx - x0) / cell, (minz - z0) / cell
    cx1, cz1 = (maxx - x0) / cell, (maxz - z0) / cell
    if maxz - minz < 0.8:
        zc = (cz0 + cz1) / 2
        return (cx0, zc, cx1, zc)
    if maxx - minx < 0.8:
        xc = (cx0 + cx1) / 2
        return (xc, cz0, xc, cz1)
    a, b = (cx0, cz0, cx1, cz1), (cx0, cz1, cx1, cz0)

    def hits(seg):
        xs, zs = line_cells(seg, n)
        return int(np.count_nonzero(kind[zs, xs] == 2)) if len(xs) else 0

    return a if hits(a) >= hits(b) else b


def bake_chunk(g, tx, tz, walls, trees, poles):
    x0, z0 = g.origin(tx, tz)
    T, S, cell = g.t_n, g.s_n, g.cell
    tile = g.tile
    tpath = os.path.join(g.raw, 'terrain', f't_{tx}_{tz}.csv')
    _, t = read_numbers(tpath)
    if t.size != T * T:
        raise ValueError(f'terrain {tx},{tz}: {t.size} values, expected {T * T}')
    t = t.reshape(T, T)
    terrain = np.clip(np.round(t / g.t_unit_cm), 0, 65535).astype(np.uint16)
    ground_m = np.maximum(t, 0) / 100.0              # water line clamp, metres

    top = np.zeros((S, S), np.uint8)
    bottom = np.zeros((S, S), np.uint8)
    kind = np.zeros((S, S), np.uint8)
    cover = np.zeros((S, S), np.uint8)
    # terrain sample under each surface cell
    ratio = g.t_step / cell
    idx = np.minimum((np.arange(S) / ratio).astype(np.int64), T - 1)

    _, s = read_numbers(os.path.join(g.raw, 'surface', f's_{tx}_{tz}.csv'))
    if s.size:
        s = s.reshape(-1, 6).astype(np.int64)
        c, r = s[:, 0], s[:, 1]
        q = lambda dm: np.clip(np.round(dm / (Q * 10)), 0, 255).astype(np.uint8)
        t_q, b_q = q(s[:, 2]), q(s[:, 3])
        top[r, c] = t_q
        bottom[r, c] = np.minimum(b_q, t_q)  # a thin bush's underside can land a hair above its top
        kind[r, c] = s[:, 4]
        cover[r, c] = q(s[:, 5])
        # Below the sea the scan measured from the sea floor, but the map's ground is the water line: re-measure
        # from the water, and drop what stays under it (rocks and pier footings on the sea floor).
        floor = (t / 100.0)[np.ix_(idx, idx)]
        wet = (floor < 0) & (kind > 0)
        if wet.any():
            lift = lambda a: np.clip(np.round((floor[wet] + a[wet].astype(np.float64) * Q) / Q), 0, 255).astype(np.uint8)
            new_top, new_bottom, new_cover = lift(top), lift(bottom), lift(cover)
            gone = new_top * Q < 0.2
            top[wet], bottom[wet], cover[wet] = new_top, new_bottom, new_cover
            wz, wx = np.nonzero(wet)
            for a in (kind, top, bottom, cover):
                a[wz[gone], wx[gone]] = 0

    drawn = removed = 0
    if len(walls):
        sel = (walls[:, 3] >= x0) & (walls[:, 1] <= x0 + tile) & (walls[:, 4] >= z0) & (walls[:, 2] <= z0 + tile)
        for w in walls[sel]:
            xs, zs = line_cells(wall_segment(w, kind, x0, z0, cell, S), S)
            if not len(xs):
                continue
            ground = ground_m[idx[zs], idx[xs]]
            h = np.clip(np.round((w[5] - ground) / Q), 0, 255).astype(np.uint8)
            if w[0] == 1:
                # solid: a continuous wall at its real height, never over a building
                free = kind[zs, xs] != 1
                xs, zs, h = xs[free], zs[free], h[free]
                kind[zs, xs] = 2
                top[zs, xs] = np.maximum(top[zs, xs], h)
                bottom[zs, xs] = 0
                drawn += len(xs)
            else:
                # see-through: whatever the rays hit on the fence line (up to its own height) stops blocking
                for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                    xx, zz = np.clip(xs + dx, 0, S - 1), np.clip(zs + dz, 0, S - 1)
                    hit = (kind[zz, xx] == 2) & (top[zz, xx] <= h.astype(np.int16) + 2)
                    kind[zz[hit], xx[hit]] = 4
                    removed += int(np.count_nonzero(hit))
    # vegetation outside every listed tree's crown is a bush
    if len(trees):
        is_tree = np.zeros((S, S), bool)
        sel = (trees[:, 0] + trees[:, 2] >= x0) & (trees[:, 0] - trees[:, 2] <= x0 + tile) & \
              (trees[:, 1] + trees[:, 2] >= z0) & (trees[:, 1] - trees[:, 2] <= z0 + tile)
        for x, z, rad in trees[sel]:
            c0, c1 = int(max(0, (x - rad - x0) / cell)), int(min(S - 1, (x + rad - x0) / cell))
            r0, r1 = int(max(0, (z - rad - z0) / cell)), int(min(S - 1, (z + rad - z0) / cell))
            if c1 < c0 or r1 < r0:
                continue
            zz, xx = np.mgrid[r0:r1 + 1, c0:c1 + 1]
            inside = (x0 + (xx + 0.5) * cell - x) ** 2 + (z0 + (zz + 0.5) * cell - z) ** 2 <= rad * rad
            is_tree[zz[inside], xx[inside]] = True
        kind[(kind == 3) & ~is_tree] = 5
    # poles, lamps and masts: one solid cell at their full height
    if len(poles):
        sel = (poles[:, 0] >= x0) & (poles[:, 0] < x0 + tile) & (poles[:, 1] >= z0) & (poles[:, 1] < z0 + tile)
        for x, z, ytop in poles[sel]:
            c, r = min(S - 1, int((x - x0) / cell)), min(S - 1, int((z - z0) / cell))
            if kind[r, c] == 1:
                continue
            h = int(np.clip(round((ytop - ground_m[idx[r], idx[c]]) / Q), 0, 255))
            if h * Q >= 3:
                kind[r, c] = 2
                top[r, c] = max(top[r, c], h)
                bottom[r, c] = 0
    return terrain, ground_m, top, bottom, kind, cover, drawn, removed


def light_cells(g, ground_m, top, bottom, kind):
    """This chunk's light cells: height (dm), forest flag, canopy top / underside (m), low, crown, building (m)."""
    lt = int(round(g.tile / LIGHT_CELL))
    lb = int(round(LIGHT_CELL / g.cell))
    ti = np.minimum(((np.arange(lt) + 0.5) * LIGHT_CELL / g.t_step).astype(np.int64), g.t_n - 1)
    height = np.round(ground_m[np.ix_(ti, ti)] * 10).astype(np.int16)
    blocks = lambda a: a[:lt * lb, :lt * lb].reshape(lt, lb, lt, lb).transpose(0, 2, 1, 3).reshape(lt, lt, lb * lb)
    k, t, b = blocks(kind), blocks(top).astype(np.float32) * Q, blocks(bottom).astype(np.float32) * Q
    veg = ((k == 3) | (k == 5)) & (t >= 3)
    crown = veg.mean(axis=2)
    forest = crown >= 0.35
    low = ((((k == 3) | (k == 5)) & (b <= 1.7) & (t >= 1.7)) | ((k == 2) & (t >= 1.7))).mean(axis=2)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        ctop = np.nanpercentile(np.where(veg, t, np.nan), 75, axis=2)
        cbot = np.nanmedian(np.where(veg, b, np.nan), axis=2)
        bld = k == 1
        bh = np.nanmedian(np.where(bld, t, np.nan), axis=2)
    has = crown >= 0.1
    ctop = np.where(has, np.nan_to_num(ctop), 0)
    cbot = np.where(has, np.nan_to_num(cbot), 0)
    bh = np.where(bld.mean(axis=2) >= 0.4, np.nan_to_num(bh), 0)
    u8 = lambda a: np.clip(np.round(a), 0, 255).astype(np.uint8)
    return height, forest, u8(ctop), u8(cbot), u8(low * 255), u8(crown * 255), u8(bh)


# Helicopter landing rules (same as the field map's landing zone check).
LZ_TOUCH, LZ_SLOPE_R, LZ_R, LZ_NEAR = 6, 8, 15, 40
LZ_OK_DEG, LZ_MAX_DEG = 17, 22
LZ_SPOT_H, LZ_ROTOR_H, LZ_NEAR_H = 1.0, 2.0, 6.0
LZ_BUMP_OK, LZ_BUMP_MAX = 0.75, 1.5


def bake_lz(g, los_dir, names):
    """The landing verdict at every light cell's centre, from the baked chunks (1 m obstacle and ground grids)."""
    T, S = g.t_n, g.s_n
    tile = int(round(g.tile))
    lt = int(round(g.tile / LIGHT_CELL))
    per_m = int(round(1 / g.cell))  # surface cells per metre

    @lru_cache(maxsize=12)
    def load(tx, tz):
        path = os.path.join(los_dir, f'{tx}_{tz}.bin.gz')
        if not os.path.exists(path):
            return None
        with open(path, 'rb') as f:
            raw = gzip.decompress(f.read())
        ter = np.frombuffer(raw, '<u2', T * T).reshape(T, T).astype(np.float32) * (g.t_unit_cm / 100)
        o = T * T * 2
        top = np.frombuffer(raw, np.uint8, S * S, o).reshape(S, S)
        kind = np.frombuffer(raw, np.uint8, S * S, o + 2 * S * S).reshape(S, S)
        h = np.where((kind > 0) & (kind != 5), top.astype(np.float32) * Q, 0)
        h = h[:tile * per_m, :tile * per_m].reshape(tile, per_m, tile, per_m).max(axis=(1, 3))
        ter1 = ter[:tile, :tile] if g.t_step == 1 else ter[np.ix_(*(2 * [np.minimum((np.arange(tile) / g.t_step).astype(int), T - 1)]))]
        return ter1, h

    M = LZ_NEAR
    ys, xs = np.mgrid[-M:M + 1, -M:M + 1]
    rr = np.hypot(xs, ys)
    touch, rotor, near = rr <= LZ_TOUCH, (rr > LZ_TOUCH) & (rr <= LZ_R), (rr > LZ_R) & (rr <= LZ_NEAR)
    disc_r, sdisc = rr <= LZ_R, rr <= LZ_SLOPE_R
    tx_w, tz_w = (xs * sdisc).astype(np.float32), (ys * sdisc).astype(np.float32)
    sxx = float((xs ** 2 * sdisc).sum())
    rx_w, rz_w = (xs * disc_r).astype(np.float32), (ys * disc_r).astype(np.float32)
    rxx, rn = float((xs ** 2 * disc_r).sum()), float(disc_r.sum())
    grid = np.zeros((g.rows * lt, g.cols * lt), np.uint8)
    for name in names:
        tx, tz = map(int, name.split('_'))
        W = tile + 2 * M + 1
        ter = np.zeros((W, W), np.float32)
        obs = np.zeros((W, W), np.float32)
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                t = load(tx + dx, tz + dz)
                if t is None:
                    continue
                x0, z0 = dx * tile + M, dz * tile + M
                a0, b0 = max(0, -x0), max(0, -z0)
                a1, b1 = min(tile, W - x0), min(tile, W - z0)
                if a1 <= a0 or b1 <= b0:
                    continue
                ter[z0 + b0:z0 + b1, x0 + a0:x0 + a1] = t[0][b0:b1, a0:a1]
                obs[z0 + b0:z0 + b1, x0 + a0:x0 + a1] = t[1][b0:b1, a0:a1]
        cz = np.arange(LIGHT_CELL // 2, tile, LIGHT_CELL) + M
        view = lambda a: np.lib.stride_tricks.sliding_window_view(a, (2 * M + 1, 2 * M + 1))[cz - M][:, cz - M]
        Tw, Ow = view(ter), view(obs)
        h0 = Tw[:, :, M, M]
        zc = Tw - Tw[:, :, M:M + 1, M:M + 1]
        ax = (zc * tx_w).sum((2, 3)) / sxx
        az = (zc * tz_w).sum((2, 3)) / sxx
        slope = np.degrees(np.arctan(np.hypot(ax, az)))
        bx = (zc * rx_w).sum((2, 3)) / rxx
        bz = (zc * rz_w).sum((2, 3)) / rxx
        c0 = (zc * disc_r).sum((2, 3)) / rn
        plane = c0[:, :, None, None] + bx[:, :, None, None] * xs + bz[:, :, None, None] * ys
        bump = np.where(disc_r, zc - plane, -9).max((2, 3))
        o_touch = np.where(touch, Ow, 0).max((2, 3))
        o_rotor = np.where(rotor, Ow, 0).max((2, 3))
        o_near = np.where(near, Ow, 0).max((2, 3))
        nogo = (o_touch >= LZ_SPOT_H) | (o_rotor >= LZ_ROTOR_H) | (slope > LZ_MAX_DEG) | (bump > LZ_BUMP_MAX)
        marg = (o_near >= LZ_NEAR_H) | (slope > LZ_OK_DEG) | (bump > LZ_BUMP_OK)
        v = np.where(h0 < 0.5, 0, np.where(nogo, 3, np.where(marg, 2, 1))).astype(np.uint8)
        grid[tz * lt:(tz + 1) * lt, tx * lt:(tx + 1) * lt] = v
    return grid


def write_gz(path, arr):
    with open(path, 'wb') as f:
        f.write(gzip.compress(np.ascontiguousarray(arr).tobytes(), 9, mtime=0))


def bake(raw, site, log=print, only=None, probe=None):
    t0 = time.time()
    g = Grid(raw, probe)
    los_dir = os.path.join(site, 'los')
    light_dir = os.path.join(site, 'light')
    os.makedirs(los_dir, exist_ok=True)
    os.makedirs(light_dir, exist_ok=True)
    log(f'los: grid {g.cols}x{g.rows} of {g.tile:g} m from ({g.x0:g}, {g.z0:g}); terrain unit {g.t_unit_cm} cm')
    walls, trees, poles = load_objects(raw)
    log(f'los: {len(walls):,} walls/fences, {len(trees):,} trees, {len(poles):,} poles ({time.time() - t0:.0f} s)')

    lt = int(round(g.tile / LIGHT_CELL))
    L = {k: np.zeros((g.rows * lt, g.cols * lt), dt) for k, dt in
         (('height', np.int16), ('forest', bool), ('ctop', np.uint8), ('cbot', np.uint8), ('low', np.uint8),
          ('crown', np.uint8), ('bld', np.uint8))}
    names, total = [], 0
    chunks = [c for c in g.chunks() if only is None or f'{c[0]}_{c[1]}' in only]
    for i, (tx, tz) in enumerate(chunks):
        terrain, ground_m, top, bottom, kind, cover, _, _ = bake_chunk(g, tx, tz, walls, trees, poles)
        sl = (slice(tz * lt, (tz + 1) * lt), slice(tx * lt, (tx + 1) * lt))
        for key, val in zip(('height', 'forest', 'ctop', 'cbot', 'low', 'crown', 'bld'),
                            light_cells(g, ground_m, top, bottom, kind)):
            L[key][sl] = val
        if not terrain.any() and not kind.any():
            continue  # open sea: nothing to load
        path = os.path.join(los_dir, f'{tx}_{tz}.bin.gz')
        raw_bytes = terrain.astype('<u2').tobytes() + top.tobytes() + bottom.tobytes() + kind.tobytes() + cover.tobytes()
        with open(path, 'wb') as f:
            f.write(gzip.compress(raw_bytes, 6, mtime=0))
        total += os.path.getsize(path)
        names.append(f'{tx}_{tz}')
        if (i + 1) % 25 == 0 or i + 1 == len(chunks):
            log(f'los: {i + 1}/{len(chunks)} chunks, {len(names)} written, {total / 1e6:.0f} MB ({time.time() - t0:.0f} s)')

    write_gz(os.path.join(light_dir, 'height.bin.gz'), L['height'].astype('<i2'))
    write_gz(os.path.join(light_dir, 'forest.bin.gz'), np.packbits(L['forest'].reshape(-1)))
    write_gz(os.path.join(light_dir, 'canopy.bin.gz'), np.concatenate([L[k].reshape(-1) for k in ('ctop', 'cbot', 'low', 'crown')]))
    write_gz(os.path.join(light_dir, 'buildings.bin.gz'), L['bld'])
    lz = bake_lz(g, los_dir, names)
    write_gz(os.path.join(light_dir, 'lz.bin.gz'), lz)
    index = {
        'version': int(time.time()),
        'grid': {'x0': g.x0, 'z0': g.z0, 'tile': g.tile, 'cols': g.cols, 'rows': g.rows},
        'terrain': {'n': g.t_n, 'step': g.t_step, 'unit': g.t_unit_cm / 100, 'sea': 0},
        'surface': {'n': g.s_n, 'step': g.cell, 'unit': Q},
        'kinds': {'0': 'nothing', '1': 'building', '2': 'solid', '3': 'tree', '4': 'see-through fence', '5': 'bush'},
        'layout': ['terrain Uint16', 'top Uint8', 'bottom Uint8', 'kind Uint8', 'cover Uint8'],
        'light': {'cell': LIGHT_CELL, 'cols': g.cols * lt, 'rows': g.rows * lt,
                  'files': ['height Int16 dm', 'forest 1 bit', 'canopy Uint8 x4 (top, base, low, crown)',
                            'buildings Uint8 m', 'lz Uint8 (0 water, 1 good, 2 marginal, 3 no-go)']},
        'tiles': names,
    }
    with open(os.path.join(los_dir, 'index.json'), 'w', encoding='utf8') as f:
        json.dump(index, f)
    land = lz > 0
    if land.any():
        log(f'los: landing good {np.mean(lz[land] == 1):.0%}, marginal {np.mean(lz[land] == 2):.0%}, no-go {np.mean(lz[land] == 3):.0%}')
    log(f'los: done, {len(names)} chunks, {total / 1e6:.0f} MB ({time.time() - t0:.0f} s)')
    return index
