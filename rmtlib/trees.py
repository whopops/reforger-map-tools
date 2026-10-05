"""The website's 3D view's trees: every tree and bush, plus a crown shape and colours for each species from the
foliage measurements. Used by `rmt.py fieldmap` (rmtlib/fieldmap.py). Port of everon-3d-map's old tools/build_trees.py.

Reads:  objects/o_<tx>_<tz>.csv (the entities export), foliage/foliage_profiles.json and foliage/foliage_shots.csv
        (only the close-up "near" rows), and optionally the foliage photos for colours
Writes (to `out`, gzip -9 with no name or time, so a rebuild is byte-identical):
  species.json    { format, version, tiles: [names with trees], species: [{ name, kind, height, rmax, ring: [[y, r] x 7],
                  trunk, crown }] }
  <tx>_<tz>.bin.gz  8-byte records, little endian: Uint16 x, z (cm from the tile's corner), Uint8 species, yaw (360/256
                  degrees), height (0.25 m), crown radius (0.1 m)

A species' shape is 7 rings from the ground up: two for the trunk (bottom and top), then five for the crown, the last
one a point. y is a fraction of the species' height; r is a fraction of its widest crown radius, except for the two
trunk rings, where it is a fraction of the height. The page scales them by each tree's own bounding box, so its height
and width come straight from the game's data.
"""

import collections
import csv
import glob
import gzip
import hashlib
import io
import json
import os
import re

CROWN_FRACTIONS = (0.03, 0.22, 0.45, 0.72, 1.0)   # where the crown rings sit between crown base and crown top
FORMAT = 2                                         # 2: trunk ring radii are fractions of the height


def write_gz(path, data):
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as g:
        g.write(data)
    with open(path, "wb") as f:
        f.write(buf.getvalue())


def vivid(c, sat, gain):
    lum = 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
    return [int(min(255, max(0, (lum + (v - lum) * sat) * gain))) for v in c]


def smooth(v):
    return [(v[max(i - 1, 0)] + 2 * v[i] + v[min(i + 1, len(v) - 1)]) / 4 for i in range(len(v))]


def interp(ys, ws, y):
    if y <= ys[0]:
        return ws[0]
    for i in range(1, len(ys)):
        if y <= ys[i]:
            t = (y - ys[i - 1]) / (ys[i] - ys[i - 1])
            return ws[i - 1] + (ws[i] - ws[i - 1]) * t
    return ws[-1]


def rings_for(height, slices, raw_slices=None):
    """slices: [(y_bottom, mean_width_m)] every 0.5 m. Returns 7 [y, r] rings as fractions."""
    ys = [y + 0.25 for y, _ in slices]
    ws = smooth([w for _, w in slices])
    wmax = max(ws)
    rmax = wmax / 2
    top = max((y + 0.5 for (y, _), w in zip(slices, ws) if w > 0.03 * wmax), default=height)
    top = min(max(top, 1.0), height)
    base = next((y for y, w in zip(ys, ws) if w >= 0.45 * wmax), 0.0)
    base = min(max(base - 0.25, 0.0), top - 0.6)
    # Trunk diameter. Measured on a bare stem: the narrowest slice between the ground flare and the crown (branch stubs
    # only ever make a slice wider, so the minimum is the trunk). Where the crown reaches the ground the trunk is hidden
    # in it, so use the rule the measured trees follow: about 1.9% of their height. Kept within 1.2-3% of the height.
    raw = [(y, sum(v) / len(v)) for y, v in sorted(raw_slices.items())] if raw_slices else slices
    stem = [w for y, w in raw if 0.75 <= y < base - 0.5]
    diameter = min(stem) if base >= 1.5 and stem else 0.019 * height
    diameter = min(max(diameter, 0.012 * height), 0.03 * height)
    trunk = max(diameter / 2, 0.05)
    if base < 0.3:
        base = 0.0
    span = top - base
    # the two trunk rings hold a fraction of the tree's height (not of its crown radius), so a trunk is as thick as a
    # tree of that height really has; the ground flare is a little wider than the trunk above it
    ring = [[0.0, trunk * 1.15], [base if base > 0 else 0.02 * span, trunk]]
    for i, f in enumerate(CROWN_FRACTIONS):
        y = base + f * span
        r = 0.0 if i == len(CROWN_FRACTIONS) - 1 else interp(ys, ws, y) / 2
        if i == 0:
            r *= 0.8                                  # the underside of the crown is rounder than a straight cut
        ring.append([y, r])
    out = [[round(y / height, 4), round(min(r / rmax, 1.0), 4)] for y, r in ring]
    for i in (0, 1):
        out[i][1] = round(ring[i][1] / height, 5)
    return out, rmax


def photo_colours(photos, prefab_files):
    """{prefab file id: (trunk rgb, crown rgb)} from the photographed views: pixels that differ between the shot with
    the plant and the shot without are the plant; the lowest slice of its outline is trunk, the top half is crown."""
    import numpy as np
    from PIL import Image
    out = {}
    for name, ident in prefab_files.items():
        trunk, crown, nt, nc = np.zeros(3), np.zeros(3), 0, 0
        # four sides spread round the plant (the old Everon export has 16 close-up sides, reforger-map-tools 8)
        sides = [s for s in range(16) if os.path.isfile(os.path.join(photos, f"{ident}_0_{s}_a.png"))]
        for side in sides[::max(1, len(sides) // 4)]:
            fa = os.path.join(photos, f"{ident}_0_{side}_a.png")
            fb = fa.replace("_a.png", "_b.png")
            if not (os.path.isfile(fa) and os.path.isfile(fb)):
                continue
            a = np.asarray(Image.open(fa).convert("RGB")).astype(int)
            b = np.asarray(Image.open(fb).convert("RGB")).astype(int)
            m = (np.abs(a - b).sum(2) > 60) & (a[:, :, 2] < a[:, :, 0] + 12)   # blue-ish changes are sky or sea, not plant
            rows = np.nonzero(m.any(1))[0]
            if len(rows) < 20:
                continue
            r0, r1 = rows[0], rows[-1]
            h = r1 - r0
            lo = m.copy(); lo[: r1 - int(h * 0.12)] = False
            hi = m.copy(); hi[r0 + int(h * 0.5):] = False
            if lo.any(): trunk += a[lo].sum(0); nt += lo.sum()
            if hi.any(): crown += a[hi].sum(0); nc += hi.sum()
        if nc:
            c = crown / nc
            t = trunk / nt if nt else c * 0.7
            out[name] = ([int(v) for v in t], [int(v) for v in c])
    return out


def build(objects, foliage, out, photos=None, log=print):
    """Write the tree tiles and species.json into `out` (emptied first). Colours come from the photos in `photos`, or
    plain tree and bush greens without them. Returns the species table."""
    with open(os.path.join(foliage, "foliage_profiles.json"), encoding="utf-8") as f:
        profiles = json.load(f)
    widths = collections.defaultdict(lambda: collections.defaultdict(list))
    with open(os.path.join(foliage, "foliage_shots.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("band", "near") != "near":
                continue
            widths[r["prefab"]][float(r["slice_m"])].append(float(r["width_m"]))

    species, index, files = [], {}, {}
    for prefab in sorted(profiles, key=lambda p: p.split("/")[-1]):
        name = prefab.split("/")[-1][:-3]
        p = profiles[prefab]
        slices = [(y, sum(w) / len(w)) for y, w in sorted(widths[prefab].items())]
        ring, rmax = rings_for(p["height"], slices, widths[prefab])
        index[name] = len(species)
        files[name] = re.match(r"\{([0-9A-F]+)\}", prefab).group(1)
        species.append({"name": name, "kind": p["kind"], "height": round(p["height"], 2), "rmax": round(rmax, 2), "ring": ring})
    cols = {}
    if photos:
        ids = {}
        for f in sorted(os.listdir(photos)):
            m = re.match(r"(.+_[0-9A-F]{16})_0_0_a\.png$", f)
            if m:
                ids[m.group(1).rsplit("_", 1)[0]] = m.group(1)
        log("trees: reading photo colours…")
        cols = photo_colours(photos, {n: ids[n] for n in index if n in ids})
    for s in species:
        s["trunk"], s["crown"] = cols.get(s["name"], ([95, 75, 55], [60, 100, 55] if s["kind"] == "tree" else [75, 110, 55]))
        # the lowest part of a photo picks up glare, and a bush has no trunk: use bark-dark values
        s["trunk"] = [int(c * 0.75) for c in s["crown"]] if s["kind"] == "bush" else [min(c, 120) for c in s["trunk"]]
        # the photos were taken under flat, hazy light: put back the colour that light washed out
        s["crown"], s["trunk"] = vivid(s["crown"], 2.4, 1.05), vivid(s["trunk"], 1.5, 0.9)

    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "*")):
        os.remove(old)
    tiles, total, biggest = [], 0, [0, 0]
    for path in sorted(glob.glob(os.path.join(objects, "o_*_*.csv"))):
        tx, tz = map(int, re.match(r"o_(\d+)_(\d+)\.csv$", os.path.basename(path)).groups())
        data = bytearray()
        with open(path, encoding="utf-8") as f:
            next(f)
            for line in f:
                if "/Vegetation/" not in line:
                    continue
                c = line.rstrip("\n").split(",")
                name = c[1].rsplit("/", 1)[-1][:-3]
                sp = index.get(name)
                if sp is None:
                    continue                        # stumps, fallen trunks, crops, debris: left as they are
                x, z, yaw = float(c[2]) - 500 * tx, float(c[4]) - 500 * tz, float(c[5])
                h = float(c[13]) - float(c[10])
                r = ((float(c[12]) - float(c[9])) + (float(c[14]) - float(c[11]))) / 4
                biggest = [max(biggest[0], h), max(biggest[1], r)]
                data += int(min(max(round(x * 100), 0), 65535)).to_bytes(2, "little")
                data += int(min(max(round(z * 100), 0), 65535)).to_bytes(2, "little")
                data += bytes([sp, int(yaw % 360 / 360 * 256) & 255, min(255, max(1, round(h / 0.25))), min(255, max(1, round(r / 0.1)))])
        if data:
            write_gz(os.path.join(out, f"{tx}_{tz}.bin.gz"), bytes(data))
            tiles.append(f"{tx}_{tz}")
            total += len(data) // 8
    # format: bumped whenever the meaning of a field changes, so an old page never misreads a new table (or the
    # reverse). version: a hash of everything written, used to cache-bust the tree files.
    h = hashlib.sha1(json.dumps(species, sort_keys=True).encode())
    for name in tiles:
        with open(os.path.join(out, f"{name}.bin.gz"), "rb") as f:
            h.update(f.read())
    table = {"format": FORMAT, "version": h.hexdigest()[:12], "tiles": tiles, "species": species}
    with open(os.path.join(out, "species.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(table, f, separators=(",", ":"))
        f.write("\n")
    log(f"trees: {total} trees and bushes in {len(tiles)} tiles, {len(species)} species; tallest {biggest[0]:.1f} m, "
        f"widest radius {biggest[1]:.1f} m (limits 63.75 m and 25.5 m)")
    return table
