"""Every standing tree and bush on the map, and the 10 m foliage / clutter light layers, for the site.

Port of arma-map/everon-map/tools/foliage_model.py and bake_light_foliage.py (the field map's "Visual" and "Light"
line of sight), made map-independent and fed with this exporter's own measurements:
  - the plants come from the entities export (every standing tree / bush prefab, as foliage.plant_list picks them),
  - each kind's shape and see-through from the foliage job's close-up measurements (site/foliage/foliage_shots.csv),
  - the ground under each plant, the grid and the light size from the baked LOS tiles (site/los/index.json).

Output:
  site/foliage.json          {"bins": 10, "margin": 16, "baseUnit": <m>, "tiles": [...], "prefabs": [...],
                              "plants": [{"h", "hw": [10], "k": [10]}, ...]}
                             per kind (index = the kind byte in the tiles; prefabs[i] is its prefab, the key into
                             foliage/foliage_profiles.json): its height h (m, scale 1) and, per tenth of that height,
                             half-width hw (m) and k (per metre crossed; what is left visible is e^(-sum k x metres)).
  site/plants/<tx>_<tz>.bin.gz  per 500 m chunk, every plant reaching into it, little endian:
                             n Uint32, x Uint16[n], z Uint16[n] (cm from `margin` m south-west of the chunk's corner),
                             base Uint16[n] (ground under it, in baseUnit metres: 0.01 unless the map is too high for
                             cm, e.g. Kolguyev 0.02), kind Uint8[n], scale Uint8[n] (hundredths)
  site/light/foliage.bin.gz  Uint8[bands][rows*cols]: per 10 m cell and height band (edges 0,1,2,4,7,12,20,45 m) the
                             average foliage k, 0-255 = 0-0.5 per metre
  site/light/clutter.bin.gz  Uint8[bands][rows*cols]: per cell and band the share filled by solid things, 0-255 = 0-100%
The layouts are the field map's own, except baseUnit (the old files assume cm) and prefabs (new).
"""

import collections
import csv
import gzip
import json
import math
import os
import statistics
import time

import numpy as np

from .bake_los import iter_objects
from .foliage import standing_plant

BINS = 10
MARGIN = 16
BANDS = [0, 1, 2, 4, 7, 12, 20, 45]
K_MAX = 0.5
LIGHT_CELL = 10


def kind_profiles(shots_csv, prefabs):
    """h, hw[BINS], k[BINS] per prefab from the close-up measurements (same method as the field map's model)."""
    shots = collections.defaultdict(list)
    with open(shots_csv, encoding="utf8", newline="") as f:
        for r in csv.DictReader(f):
            if r["band"] == "near":
                shots[r["id"]].append(r)
    by_prefab = collections.defaultdict(list)
    for s in shots.values():
        by_prefab[s[0]["prefab"]].append(s)
    ys = sorted({float(x["slice_m"]) for s in shots.values() for x in s})
    step = min(b - a for a, b in zip(ys, ys[1:])) if len(ys) > 1 else 0.25
    out = []
    for prefab in prefabs:
        tops, slices = [], collections.defaultdict(list)
        for s in by_prefab[prefab]:
            tops.append(max([float(x["slice_m"]) + step for x in s if float(x["cover"]) > 0.02] or [step]))
            for x in s:
                w = float(x["width_m"])
                slices[float(x["slice_m"])].append((float(x["cover"]) * w, w))
        h = statistics.median(tops) if tops else step
        hw, ks = [], []
        for j in range(BINS):
            lo, hi = j * h / BINS, (j + 1) * h / BINS
            sel = [y for y in slices if lo <= y + step / 2 < hi] or [math.floor((lo + hi) / 2 / step) * step]
            pairs = [p for y in sel for p in slices.get(y, [])]
            w = float(np.mean([p[1] for p in pairs])) if pairs else 0
            blocked = float(np.mean([p[0] for p in pairs])) if pairs else 0
            if w < 0.05:
                hw.append(0)
                ks.append(0)
                continue
            cover = min(0.99, blocked / w)
            hw.append(round(w / 2, 3))
            ks.append(round(-math.log(1 - cover) / w, 4))
        out.append({"h": round(h, 2), "hw": hw, "k": ks})
    return out


class Ground:
    """Ground height (m, sea at 0) anywhere, from the baked LOS tiles."""

    def __init__(self, site, index):
        self.site, self.i = site, index
        self.tile = index["grid"]["tile"]
        self.x0, self.z0 = index["grid"]["x0"], index["grid"]["z0"]
        self.n = index["terrain"]["n"]
        self.unit = index["terrain"]["unit"]
        self.names = set(index["tiles"])
        self.cache = {}

    def chunk(self, tx, tz):
        key = (tx, tz)
        if key not in self.cache:
            name = f"{tx}_{tz}"
            if name not in self.names:
                self.cache[key] = None
            else:
                with gzip.open(os.path.join(self.site, "los", name + ".bin.gz")) as f:
                    raw = f.read(self.n * self.n * 2)
                self.cache[key] = np.frombuffer(raw, "<u2").reshape(self.n, self.n).astype(np.float64) * self.unit
        return self.cache[key]

    def at(self, x, z):
        tx, tz = int((x - self.x0) // self.tile), int((z - self.z0) // self.tile)
        t = self.chunk(tx, tz)
        if t is None:
            return 0.0
        step = self.i["terrain"]["step"]
        lx = min(max((x - self.x0 - tx * self.tile) / step, 0), self.n - 1 - 1e-6)
        lz = min(max((z - self.z0 - tz * self.tile) / step, 0), self.n - 1 - 1e-6)
        c, r = int(lx), int(lz)
        fx, fz = lx - c, lz - r
        a, b, d, e = t[r, c], t[r, c + 1], t[r + 1, c], t[r + 1, c + 1]
        return float((a + (b - a) * fx) * (1 - fz) + (d + (e - d) * fx) * fz)


def foliage_layer(x, z, kind, scale, prof, rows, cols, x0, z0):
    nb = len(BANDS) - 1
    k_grid = np.zeros((nb, rows, cols), np.float64)
    for kd, p in enumerate(prof):
        sel = kind == kd
        if not sel.any():
            continue
        px, pz, s = x[sel] - x0, z[sel] - z0, scale[sel]
        h = p["h"] * s
        for j in range(BINS):
            if not p["k"][j] or not p["hw"][j]:
                continue
            half = p["hw"][j] * s * np.sqrt(np.pi) / 2
            k = p["k"][j] / s
            y0, y1 = h * j / BINS, h * (j + 1) / BINS
            share = [np.clip(np.minimum(y1, BANDS[b + 1]) - np.maximum(y0, BANDS[b]), 0, None) / (BANDS[b + 1] - BANDS[b])
                     for b in range(nb)]
            cx0 = np.floor((px - half) / LIGHT_CELL).astype(int)
            cz0 = np.floor((pz - half) / LIGHT_CELL).astype(int)
            span = int(np.ceil(2 * half.max() / LIGHT_CELL)) + 1 if len(half) else 1
            for dz in range(span):
                for dx in range(span):
                    cx, cz = cx0 + dx, cz0 + dz
                    ox = np.clip(np.minimum(px + half, (cx + 1) * LIGHT_CELL) - np.maximum(px - half, cx * LIGHT_CELL), 0, None)
                    oz = np.clip(np.minimum(pz + half, (cz + 1) * LIGHT_CELL) - np.maximum(pz - half, cz * LIGHT_CELL), 0, None)
                    area = ox * oz / (LIGHT_CELL * LIGHT_CELL)
                    ok = (area > 0) & (cx >= 0) & (cx < cols) & (cz >= 0) & (cz < rows)
                    if not ok.any():
                        continue
                    for b in range(nb):
                        w = (k * area * share[b])[ok]
                        if w.any():
                            np.add.at(k_grid[b], (cz[ok], cx[ok]), w)
    return k_grid


def clutter_layer(site, index, rows, cols):
    nb = len(BANDS) - 1
    S, T, Q = index["surface"]["n"], index["terrain"]["n"], index["surface"]["unit"]
    per = int(round(index["grid"]["tile"] / LIGHT_CELL))
    blk = S // per
    grid = np.zeros((nb, rows, cols), np.float32)
    for name in index["tiles"]:
        tx, tz = map(int, name.split("_"))
        with gzip.open(os.path.join(site, "los", name + ".bin.gz")) as f:
            raw = f.read()
        o = T * T * 2
        top = np.frombuffer(raw, np.uint8, S * S, o).reshape(S, S).astype(np.float32) * Q
        kd = np.frombuffer(raw, np.uint8, S * S, o + 2 * S * S).reshape(S, S)
        top = np.where((kd == 1) | (kd == 2), top, 0)
        for b in range(nb):
            fill = np.clip((top - BANDS[b]) / (BANDS[b + 1] - BANDS[b]), 0, 1)
            grid[b, tz * per:(tz + 1) * per, tx * per:(tx + 1) * per] = fill.reshape(per, blk, per, blk).mean(axis=(1, 3))
    return grid


def write_gz(path, arr):
    with open(path, "wb") as f:
        f.write(gzip.compress(np.ascontiguousarray(arr).tobytes(), 9, mtime=0))


def bake(raw, site, log=print):
    t0 = time.time()
    with open(os.path.join(site, "los", "index.json"), encoding="utf8") as f:
        index = json.load(f)
    prof_path = os.path.join(site, "foliage", "foliage_profiles.json")
    shots_csv = os.path.join(site, "foliage", "foliage_shots.csv")
    if not (os.path.isfile(prof_path) and os.path.isfile(shots_csv)):
        log("plants: no foliage measurements in site/foliage (run the foliage job and bake --parts foliage)")
        return None
    with open(prof_path, encoding="utf8") as f:
        prefabs = sorted(json.load(f))
    kind_of = {p: i for i, p in enumerate(prefabs)}
    prof = kind_profiles(shots_csv, prefabs)

    xs, zs, ks, ss = [], [], [], []
    missing = collections.Counter()
    for r in iter_objects(raw):
        p = r["prefab"]
        if not standing_plant(p):
            continue
        if p not in kind_of:
            missing[p] += 1
            continue
        xs.append(float(r["x"])); zs.append(float(r["z"]))
        ks.append(kind_of[p]); ss.append(float(r["scale"] or 1))
    x, z = np.array(xs), np.array(zs)
    kind = np.array(ks, np.int64)
    scale = np.clip(np.array(ss), 0.01, 2.55)
    if missing:
        log(f"plants: {sum(missing.values())} plants of {len(missing)} unmeasured kinds left out")

    ground = Ground(site, index)
    base = np.array([max(0.0, ground.at(a, b)) for a, b in zip(x, z)])
    unit = 0.01 if base.max(initial=0) < 655.35 else math.ceil(base.max() * 100 / 65535) / 100
    reach = np.array([max(p["hw"]) for p in prof])[kind] * scale
    log(f"plants: {len(x):,} plants of {len(prefabs)} kinds; base unit {unit:g} m")

    tile, gx0, gz0 = index["grid"]["tile"], index["grid"]["x0"], index["grid"]["z0"]
    folder = os.path.join(site, "plants")
    os.makedirs(folder, exist_ok=True)
    for fn in os.listdir(folder):
        if fn.endswith(".bin.gz"):
            os.remove(os.path.join(folder, fn))
    made, total = [], 0
    for tz in range(index["grid"]["rows"]):
        for tx in range(index["grid"]["cols"]):
            x0, z0 = gx0 + tx * tile, gz0 + tz * tile
            sel = np.nonzero((x + reach > x0) & (x - reach < x0 + tile) & (z + reach > z0) & (z - reach < z0 + tile))[0]
            if not len(sel):
                continue
            n = len(sel)
            data = (np.uint32(n).tobytes()
                    + np.round((x[sel] - x0 + MARGIN) * 100).astype("<u2").tobytes()
                    + np.round((z[sel] - z0 + MARGIN) * 100).astype("<u2").tobytes()
                    + np.round(base[sel] / unit).astype("<u2").tobytes()
                    + kind[sel].astype(np.uint8).tobytes()
                    + np.round(scale[sel] * 100).astype(np.uint8).tobytes())
            with open(os.path.join(folder, f"{tx}_{tz}.bin.gz"), "wb") as f:
                f.write(gzip.compress(data, 9, mtime=0))
            made.append(f"{tx}_{tz}")
            total += n
    size = sum(os.path.getsize(os.path.join(folder, f)) for f in os.listdir(folder))
    doc = {"note": "made by reforger-map-tools rmtlib/bake_plants.py; see there", "bins": BINS, "margin": MARGIN,
           "baseUnit": unit, "tiles": made, "prefabs": prefabs, "plants": prof}
    with open(os.path.join(site, "foliage.json"), "w", encoding="utf8") as f:
        json.dump(doc, f, separators=(",", ":"))
    log(f"plants: {len(made)} plant tiles, {total:,} entries, {size / 1e6:.1f} MB")

    rows, cols = index["light"]["rows"], index["light"]["cols"]
    k = foliage_layer(x, z, kind, scale, prof, rows, cols, gx0, gz0)
    write_gz(os.path.join(site, "light", "foliage.bin.gz"), np.clip(np.round(k / K_MAX * 255), 0, 255).astype(np.uint8))
    c = clutter_layer(site, index, rows, cols)
    write_gz(os.path.join(site, "light", "clutter.bin.gz"), np.round(c * 255).astype(np.uint8))
    log(f"plants: light foliage and clutter {rows}x{cols}, cells over K_MAX {(k > K_MAX).sum()} of {(k > 0).sum()} "
        f"({time.time() - t0:.0f} s)")
    return doc
