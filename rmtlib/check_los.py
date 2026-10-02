"""Score the baked line-of-sight tiles against the engine's own sight lines (the `sightlines` export job).

Port of the old Everon accuracy check (arma-map's "Check: sight lines" Workbench button, whose scores were "objects
95%, terrain alone 66%"), made map-independent.

Input:  <raw>/sightlines/check.csv   ox,oz,og,eye,tx,tz,tg,target,dist,frac_all,hit_all,frac_bullet
                                     (frac: how far along the ray got before it hit something, 1 = clear)
        <site>/los/                  the baked tiles and index.json (rmtlib/bake_los.py)

Each line is walked through the tiles every STEP metres, from NEAR metres past the observer to NEAR metres short of
the target (the eye and the chest sit right on top of their own ground). The map calls it blocked where the ground
rises above the line, or where the line passes between the underside and the top of a building, wall, rock, pole,
tree or bush on a surface cell. See-through fences don't block, as on the map. The engine calls it blocked when the
ray that stops on anything stopped short (frac_all < 1). The score is the share of lines where the two agree; the
same is given for the bare terrain, and, when the tiles carry the cover plane, for what stops bullets.

Run:  python rmt.py check <world>                       (newest export and its site)
      python rmt.py check --csv <check.csv> --site <folder with los/>
"""

import csv
import gzip
import json
import os
from collections import OrderedDict

import numpy as np

STEP = 0.25         # metres between samples along a line
NEAR = 0.5          # metres left out at each end
CLEAR = 0.999       # frac at or above this counts as a clear ray
BLOCKS = (1, 2, 3, 5)  # building, solid, tree, bush (4 = see-through fence)
DIST_BANDS = (10, 50, 200, 1000)


class Tiles:
    """The baked chunks, loaded as they are needed (a few dozen at a time)."""

    def __init__(self, los_dir, keep=48):
        with open(os.path.join(los_dir, 'index.json'), encoding='utf8') as f:
            ix = json.load(f)
        self.dir = los_dir
        g, t, s = ix['grid'], ix['terrain'], ix['surface']
        self.x0, self.z0, self.tile = float(g['x0']), float(g['z0']), float(g['tile'])
        self.T, self.t_step, self.t_unit = int(t['n']), float(t['step']), float(t['unit'])
        self.S, self.cell, self.q = int(s['n']), float(s['step']), float(s['unit'])
        self.names = set(ix['tiles'])
        self.keep = keep
        self.cache = OrderedDict()
        self.has_cover = None  # known once a tile is read (a tile trimmed to terrain, top, bottom and kind has none)

    def get(self, tx, tz):
        name = f'{tx}_{tz}'
        if name in self.cache:
            self.cache.move_to_end(name)
            return self.cache[name]
        t = None
        if name in self.names:
            with open(os.path.join(self.dir, name + '.bin.gz'), 'rb') as f:
                raw = gzip.decompress(f.read())
            T, S = self.T, self.S
            o = T * T * 2
            plane = lambda i: np.frombuffer(raw, np.uint8, S * S, o + i * S * S).reshape(S, S)
            cover = plane(3) if len(raw) >= o + 4 * S * S else None  # planes: top, bottom, kind, cover
            if self.has_cover is None:
                self.has_cover = cover is not None
            t = {'ter': np.frombuffer(raw, '<u2', T * T).reshape(T, T).astype(np.float32) * self.t_unit,
                 'top': plane(0), 'bot': plane(1), 'kind': plane(2), 'cover': cover}
        self.cache[name] = t
        while len(self.cache) > self.keep:
            self.cache.popitem(last=False)
        return t


def walk(tiles, ox, oz, oy, tx, tz, ty):
    """For one sight line: (terrain blocks, terrain or objects block, terrain or cover blocks or None)."""
    L = float(np.hypot(tx - ox, tz - oz))
    if L <= 2 * NEAR:
        return False, False, False if tiles.has_cover is not False else None
    s = np.arange(NEAR, L - NEAR, STEP)
    f = s / L
    x, z, y = ox + (tx - ox) * f, oz + (tz - oz) * f, oy + (ty - oy) * f
    cx = np.floor((x - tiles.x0) / tiles.tile).astype(np.int64)
    cz = np.floor((z - tiles.z0) / tiles.tile).astype(np.int64)
    terrain = solid = bullet = False
    cover_known = True
    for key in set(zip(cx.tolist(), cz.tolist())):
        m = (cx == key[0]) & (cz == key[1])
        t = tiles.get(*key)
        if t is None:
            continue  # open sea: nothing stands above the water line
        lx = x[m] - (tiles.x0 + key[0] * tiles.tile)
        lz = z[m] - (tiles.z0 + key[1] * tiles.tile)
        ym = y[m]
        # ground: straight lines between the terrain samples, like the engine's
        gx = np.clip(lx / tiles.t_step, 0, tiles.T - 1 - 1e-6)
        gz = np.clip(lz / tiles.t_step, 0, tiles.T - 1 - 1e-6)
        c, r = gx.astype(np.int64), gz.astype(np.int64)
        fx, fz = gx - c, gz - r
        T = t['ter']
        g = (T[r, c] * (1 - fx) + T[r, c + 1] * fx) * (1 - fz) + (T[r + 1, c] * (1 - fx) + T[r + 1, c + 1] * fx) * fz
        if np.any(g > ym):
            terrain = True
        sc = np.minimum((lx / tiles.cell).astype(np.int64), tiles.S - 1)
        sr = np.minimum((lz / tiles.cell).astype(np.int64), tiles.S - 1)
        k = t['kind'][sr, sc]
        above = ym - g
        top, bot = t['top'][sr, sc] * tiles.q, t['bot'][sr, sc] * tiles.q
        if np.any(np.isin(k, BLOCKS) & (above >= bot) & (above <= top)):
            solid = True
        if t['cover'] is None:
            cover_known = False
        elif np.any((t['cover'][sr, sc] > 0) & (above <= t['cover'][sr, sc] * tiles.q)):
            bullet = True
    return terrain, terrain or solid, (terrain or bullet) if cover_known else None


def score(check_csv, site, log=print):
    with open(check_csv, encoding='utf8', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f'no sight lines in {check_csv}')
    tiles = Tiles(os.path.join(site, 'los'))
    # observer's chunk first, so neighbouring lines reuse the loaded tiles
    rows.sort(key=lambda r: (int((float(r['oz']) - tiles.z0) // tiles.tile), int((float(r['ox']) - tiles.x0) // tiles.tile)))
    n = len(rows)
    eng, eng_b = np.zeros(n, bool), np.zeros(n, bool)
    ter, obj, bul = np.zeros(n, bool), np.zeros(n, bool), np.zeros(n, np.int8)  # bul: -1 unknown
    dist = np.zeros(n)
    hit = []
    for i, r in enumerate(rows):
        ox, oz, tx, tz = float(r['ox']), float(r['oz']), float(r['tx']), float(r['tz'])
        oy = float(r['og']) + float(r['eye'])
        ty = float(r['tg']) + float(r['target'])
        a, b, c = walk(tiles, ox, oz, oy, tx, tz, ty)
        ter[i], obj[i], bul[i] = a, b, -1 if c is None else int(c)
        eng[i] = float(r['frac_all']) < CLEAR
        eng_b[i] = float(r['frac_bullet']) < CLEAR
        dist[i] = float(r['dist'])
        hit.append(r['hit_all'])
        if (i + 1) % 5000 == 0:
            log(f'check: {i + 1:,}/{n:,} lines')

    pct = lambda a: f'{100 * np.mean(a):.1f}%'
    log(f'check: {n:,} engine sight lines, {pct(eng)} blocked in the game')
    log(f'check: objects and terrain agree with the engine on {pct(obj == eng)} '
        f'(map blocks, game clear {pct(obj & ~eng)}; game blocks, map clear {pct(eng & ~obj)})')
    log(f'check: terrain alone agrees on {pct(ter == eng)}')
    known = bul >= 0
    if known.all():
        log(f'check: bullets (terrain and cover) agree on {pct((bul == 1) == eng_b)}')
    else:
        log('check: bullets not scored (these tiles have no cover plane)')
    for lo, hi in zip(DIST_BANDS, DIST_BANDS[1:]):
        m = (dist >= lo) & (dist < hi)
        if m.any():
            log(f'check:   {lo}-{hi} m: {m.sum():,} lines, agree {pct(obj[m] == eng[m])}')
    # what the engine hit where the map saw nothing, the likeliest gaps in the bake
    missed = {}
    for h, e, o in zip(hit, eng, obj):
        if e and not o:
            missed[h] = missed.get(h, 0) + 1
    if missed:
        top = sorted(missed.items(), key=lambda kv: -kv[1])[:6]
        log('check: game blocks, map clear, by what the engine hit: ' + ', '.join(f'{k or "?"} {v}' for k, v in top))
    return {'lines': n, 'agree': float(np.mean(obj == eng)), 'terrain': float(np.mean(ter == eng)),
            'bullets': float(np.mean((bul == 1) == eng_b)) if known.all() else None}
