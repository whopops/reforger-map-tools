"""How see-through each kind of tree and bush is, from the foliage photographs (the foliage job).

The foliage job photographs one plant of every standing tree and bush kind on the map, alone in an empty world, from
8 sides close up (the plant is turned, the camera stays put), once from straight below against the sky, and from the
8 sides again at each fixed distance (default 25, 50, 100, 200, 300 m) - at range the game draws simpler,
denser models (a tall spruce reads 0.56 close up, 0.79 at 150 m), so line of sight needs cover by distance. Every
view twice, with the plant shown (<id>_a) and hidden (<id>_b); the pixels that differ are where the plant blocks the
view. The camera is a standing player's eye (1.7 m above the plant's base), so what is behind the plant is sky or
distant land; the shown/hidden pair tells the plant from it. Physics rays
can't do this: every ray setting the engine has goes through leaves and only hits trunks and branches.

Side views (port of arma-map/everon-map/tools/measure_foliage.py, unchanged method): the plant is cut into 0.5 m
slices by height above its base; per slice, cover = share of the plant's outline that blocks the view, and
k = how fast it blocks sight per metre crossed (cover = 1 - e^(-k * width), taking the plant as deep as it is wide).
Top view (new): the crown from straight below, against the sky: its width and the share of it that blocks.

Output (<run>/foliage/ and site/foliage/):
  foliage_shots.csv      id,prefab,kind,band,slice_m,cover,k,width_m,pixels  (band: near or metres)
  foliage_profiles.json  {prefab: {kind, shots, height,
                                   slices: [{y, cover, k, n, px}]            (close up, as before)
                                   top: {cover, width_m}                     (crown from below)
                                   bands: [{d, near?, slices: [{y, cover, k, n, px}]}, ...]}}
                         A bush's close-up band and its 25 m band also carry "map": {cell, rows}: a grid of
                         0.25 m cells, rows from the base up, columns across the plant, whole percent blocked
                         (-1 = outside the pictures). Layers describe trees well; a bush's holes are not layered.
                         bands run from the close-up (d = its median camera distance) out to the farthest distance;
                         a viewer's line of sight through a plant d metres away uses the cover interpolated between
                         the two bands either side of d. px = pixels behind a slice's number (small = less sure).
  debug/<id>.png         the first shots with what counted as plant tinted red and the slice lines drawn
"""

import collections
import csv
import json
import math
import os

import numpy as np
from PIL import Image

SLICE = 0.25        # metres (0.25 scored 5-8 points better than 0.5 on Everon's 70 plants)
CELL = 0.25         # metres: cells of a bush's 2D map
MAP_BANDS = ("near", 25)  # a bush's 2D map beats layers only close up and at 25 m
THRESHOLD = 24      # 0-255: how much a pixel must change to count as blocked by the plant
MIN_ROWS = 2        # a slice needs at least this many image rows to be measured
SPECK_PX = 40       # changed-pixel pieces smaller than this, away from the plant, are terrain flicker (see clean)


# ------------------------------------------------------------------------------------------------ plant list
def standing_plant(prefab):
    if "/Vegetation/Tree/" not in prefab and "/Vegetation/Bush/" not in prefab:
        return False
    low = prefab.lower()
    return not any(w in low for w in ("/debris/", "_stump", "_branch", "_fallen"))


def plant_list(raw, out_csv, limit=0):
    """Every standing tree and bush kind in the entities export, most common first: prefab,kind,count,mean_scale."""
    count, scale = collections.Counter(), collections.defaultdict(float)
    folder = os.path.join(raw, "objects")
    for fn in os.listdir(folder):
        if not fn.endswith(".csv"):
            continue
        with open(os.path.join(folder, fn), encoding="utf8", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                p = r["prefab"]
                if standing_plant(p):
                    count[p] += 1
                    scale[p] += float(r["scale"] or 1)
    kinds = count.most_common(limit or None)
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", encoding="utf8", newline="") as f:
        f.write("prefab,kind,count,mean_scale\n")
        for p, n in kinds:
            kind = "tree" if "/Vegetation/Tree/" in p else "bush"
            f.write(f"{p},{kind},{n},{scale[p] / n:.4f}\n")
    return len(kinds)


# ------------------------------------------------------------------------------------------------ storage
def bmp_to_png(folder, min_age=10.0):
    """Turn the game's BMP screenshots (6.2 MB) into lossless PNG (about 1 MB), keeping every pixel. A BMP is only
    removed after its PNG has been written and read back at the same size. Files younger than min_age seconds may
    still be being written and are left for the next pass. Returns how many were converted."""
    import time
    done = 0
    now = time.time()
    for fn in os.listdir(folder):
        if not fn.endswith(".bmp"):
            continue
        src = os.path.join(folder, fn)
        if now - os.path.getmtime(src) < min_age:
            continue
        dst = src[:-4] + ".png"
        try:
            with Image.open(src) as im:
                im.load()
                size = im.size
                im.save(dst + ".part", "PNG", compress_level=6)
            with Image.open(dst + ".part") as check:
                if check.size != size:
                    raise ValueError("size changed")
            os.replace(dst + ".part", dst)
            os.remove(src)
            done += 1
        except Exception:
            if os.path.exists(dst + ".part"):
                os.remove(dst + ".part")
    return done


# ------------------------------------------------------------------------------------------------ measuring
def image_path(src, stem):
    for ext in (".bmp", ".png", ".bmp.png"):
        if os.path.isfile(os.path.join(src, stem + ext)):
            return os.path.join(src, stem + ext)
    return None


def load_rgb(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float32)


def camera(row, w, h):
    """The camera's position, axes and focal length (pixels) for a shot."""
    cam = np.array([float(row["camx"]), float(row["camy"]), float(row["camz"])])
    dx, dz = float(row["dirx"]), float(row["dirz"])
    p = math.radians(float(row["pitch"]))
    fwd = np.array([dx * math.cos(p), math.sin(p), dz * math.cos(p)])
    right = np.array([dz, 0.0, -dx])
    up = np.cross(fwd, right)
    f = (h / 2) / math.tan(math.radians(float(row["fov"])) / 2)
    return cam, fwd, right, up, f


def project(points, cam, fwd, right, up, f, w, h):
    """World points (N x 3: x, y up, z north) to pixel columns and rows."""
    rel = np.asarray(points, dtype=np.float64) - cam
    z = rel @ fwd
    u = w / 2 + f * (rel @ right) / z
    v = h / 2 - f * (rel @ up) / z
    return u, v, z


def blocked_mask(row, src):
    """(a, blocked mask, box u0,u1,v0,v1, camera, exposure ratio) for one shot."""
    pa, pb = image_path(src, row["id"] + "_a"), image_path(src, row["id"] + "_b")
    if not pa or not pb:
        raise FileNotFoundError("missing picture")
    a, b = load_rgb(pa), load_rgb(pb)
    if a.shape != b.shape:
        raise ValueError("the two screenshots are different sizes")
    h, w = a.shape[:2]
    cam = camera(row, w, h)
    mn = [float(row[k]) for k in ("minx", "miny", "minz")]
    mx = [float(row[k]) for k in ("maxx", "maxy", "maxz")]
    corners = np.array([[x, y, z] for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])])
    u, v, _ = project(corners, *cam, w, h)
    pad = 0.03 * w
    u0, u1 = int(max(0, u.min() - pad)), int(min(w, u.max() + pad))
    v0, v1 = int(max(0, v.min() - pad)), int(min(h, v.max() + pad))
    if u1 - u0 < 4 or v1 - v0 < 4:
        raise ValueError("the plant is outside the picture")
    # even out exposure: the brightness ratio between the images away from the plant
    lum_a, lum_b = a.mean(axis=2), b.mean(axis=2)
    outside = np.ones((h, w), bool)
    outside[v0:v1, u0:u1] = False
    ok = outside & (lum_b > 12) & (lum_a > 12)
    ratio = float(np.median(lum_a[ok] / lum_b[ok])) if ok.sum() > 1000 else 1.0
    diff = np.abs(a - b * ratio).max(axis=2)
    blocked = np.zeros((h, w), bool)
    # the horizon's row: a far point straight ahead at the camera's height
    pos, fwd = cam[0], cam[1]
    flat = np.array([fwd[0], 0.0, fwd[2]])
    _, vh, _ = project([pos + flat / max(np.linalg.norm(flat), 1e-9) * 1e5], *cam, w, h)
    blocked[v0:v1, u0:u1] = clean(diff[v0:v1, u0:u1] > THRESHOLD, int(math.floor(vh[0])) - 2 - v0)
    return a, blocked, (u0, u1, v0, v1), cam, ratio


def clean(mask, ground_row=0):
    """Drop specks that are not the plant, in the rows from ground_row down (where the plant is seen against terrain,
    below eye height). There, grass and ground detail flicker between the two pictures and leave single changed pixels
    all over the box; one on each side made a trunk slice measure as wide as the box. Against the sky nothing flickers
    and a distant crown's loose pieces are real, so the rows above are left alone. Kept below: pieces of at least
    SPECK_PX pixels, and any piece within a few pixels of the plant's main body (loose leaves)."""
    from scipy import ndimage as ndi
    ground_row = max(0, ground_row)
    if ground_row >= mask.shape[0]:
        return mask
    lab, n = ndi.label(mask, structure=np.ones((3, 3), bool))
    if n <= 1:
        return mask
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    big = sizes >= SPECK_PX
    big[int(sizes.argmax())] = True
    body = big[lab]
    reach = max(3, int(0.02 * max(mask.shape)))
    near = ndi.binary_dilation(body, iterations=reach)
    keep = big.copy()
    keep[np.unique(lab[near & mask])] = True
    keep[0] = False
    out = mask.copy()
    out[ground_row:] = keep[lab[ground_row:]]
    return out


def cell_map(row, blocked, cam, w, h):
    """The plant as a grid of CELL-metre cells, height up and sideways across (from the plant's axis, as the camera
    sees it): each cell is the share of that patch of the picture that the plant blocks. NaN where the cell is
    outside the picture."""
    cx, cz, ground, height = float(row["x"]), float(row["z"]), float(row["ground"]), float(row["height"])
    half = max(abs(float(row["minx"]) - cx), abs(float(row["maxx"]) - cx),
               abs(float(row["minz"]) - cz), abs(float(row["maxz"]) - cz))
    n = max(1, int(math.ceil(half / CELL)))
    nj = max(1, int(math.ceil(height / CELL)))
    pos, fwd, right, up, f = cam
    depth = float(np.dot(np.array([cx, ground, cz]) - pos, fwd))
    blk = max(1.0, CELL / (depth / f))
    ii = np.zeros((h + 1, w + 1), np.float64)
    ii[1:, 1:] = blocked.astype(np.float32).cumsum(0).cumsum(1)
    out = np.full((nj, 2 * n), np.nan)
    axis = np.array([cx, ground, cz])
    for j in range(nj):
        for i in range(2 * n):
            p = axis + np.array([0, (j + 0.5) * CELL, 0]) + right * ((i + 0.5 - n) * CELL)
            u, v, _ = project([p], pos, fwd, right, up, f, w, h)
            x0, x1 = int(round(u[0] - blk / 2)), int(round(u[0] + blk / 2))
            y0, y1 = int(round(v[0] - blk / 2)), int(round(v[0] + blk / 2))
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 <= x0 or y1 <= y0:
                continue
            out[j, i] = (ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]) / ((x1 - x0) * (y1 - y0))
    return out


def measure_side(row, src, debug_dir=None, want_map=False):
    a, blocked, (u0, u1, v0, v1), cam, ratio = blocked_mask(row, src)
    h, w = a.shape[:2]
    cx, cz, ground, height = float(row["x"]), float(row["z"]), float(row["ground"]), float(row["height"])
    depth = float(np.dot(np.array([cx, ground, cz]) - cam[0], cam[1]))
    m_per_px = depth / cam[4]
    out = []
    n_slices = int(math.ceil(height / SLICE))
    for i in range(n_slices):
        y0, y1 = i * SLICE, min((i + 1) * SLICE, height)
        _, vv, _ = project([[cx, ground + y0, cz], [cx, ground + y1, cz]], *cam, w, h)
        r0, r1 = int(max(v0, math.floor(min(vv)))), int(min(v1, math.ceil(max(vv))))
        if r1 - r0 < MIN_ROWS:
            continue
        band = blocked[r0:r1, u0:u1]
        cols = np.nonzero(band.any(axis=0))[0]
        if not len(cols):
            out.append(dict(y=y0, cover=0.0, k=0.0, width=0.0, px=0))
            continue
        c0, c1 = cols[0], cols[-1] + 1
        area = band[:, c0:c1]
        cover = float(area.mean())
        width = (c1 - c0) * m_per_px
        k = -math.log(max(1e-3, 1 - min(cover, 0.999))) / max(width, 0.25)
        out.append(dict(y=y0, cover=round(cover, 4), k=round(k, 4), width=round(width, 3), px=int(area.size)))
    if debug_dir is not None:
        img = a.copy()
        img[blocked] = img[blocked] * 0.4 + np.array([255, 0, 0]) * 0.6
        for i in range(n_slices + 1):
            _, vv, _ = project([[cx, ground + i * SLICE, cz]], *cam, w, h)
            r = int(round(vv[0]))
            if 0 <= r < h:
                img[r, u0:u1] = [255, 255, 0]
        os.makedirs(debug_dir, exist_ok=True)
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(os.path.join(debug_dir, row["id"] + ".png"))
    return out, ratio, (cell_map(row, blocked, cam, w, h) if want_map else None)


def measure_top(row, src, debug_dir=None):
    """The crown seen from straight below, against the sky: its width (m) and the share of it that blocks."""
    a, blocked, _, cam, ratio = blocked_mask(row, src)
    h, w = a.shape[:2]
    mn = [float(row[k]) for k in ("minx", "miny", "minz")]
    mx = [float(row[k]) for k in ("maxx", "maxy", "maxz")]
    mid = (mn[1] + mx[1]) / 2
    corners = np.array([[x, mid, z] for x in (mn[0], mx[0]) for z in (mn[2], mx[2])])
    u, v, _ = project(corners, *cam, w, h)
    u0, u1 = int(max(0, u.min())), int(min(w, u.max()))
    v0, v1 = int(max(0, v.min())), int(min(h, v.max()))
    if u1 - u0 < 4 or v1 - v0 < 4:
        raise ValueError("the plant is outside the picture")
    if debug_dir is not None:
        img = a.copy()
        img[blocked] = img[blocked] * 0.4 + np.array([255, 0, 0]) * 0.6
        img[v0:v1, [u0, u1 - 1]] = [0, 255, 255]
        img[[v0, v1 - 1], u0:u1] = [0, 255, 255]
        os.makedirs(debug_dir, exist_ok=True)
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(os.path.join(debug_dir, row["id"] + ".png"))
    # The crown: a circle round the plant's middle holding 95% of the blocked pixels in its box footprint (the box is
    # often far wider than the leaves); cover is the blocked share of that circle.
    cu, cv, _ = project([[float(row["x"]), mid, float(row["z"])]], *cam, w, h)
    ys, xs = np.nonzero(blocked[v0:v1, u0:u1])
    if not len(xs):
        return dict(cover=0.0, width_m=0.0), ratio
    r = np.hypot(xs + u0 - cu[0], ys + v0 - cv[0])
    radius = max(2.0, float(np.percentile(r, 95)))
    yy, xx = np.mgrid[0:h, 0:w]
    disc = np.hypot(xx - cu[0], yy - cv[0]) <= radius
    depth = abs(float(row["camy"]) - mid)
    m_per_px = max(depth, 0.1) / cam[4]
    return dict(cover=round(float(blocked[disc].mean()), 4),
                width_m=round(2 * radius * m_per_px, 2)), ratio


def analyse(src, out_dirs=(), debug=20, log=print):
    """Measure every shot in src (the foliage folder with shots.csv) and write the results to src and out_dirs."""
    with open(os.path.join(src, "shots.csv"), encoding="utf8", newline="") as f:
        rows = list({r["id"]: r for r in csv.DictReader(f)}.values())  # a view shot again: keep the last
    per_kind, lines, bad = {}, [], 0
    for n, row in enumerate(rows):
        dbg = os.path.join(src, "debug") if debug < 0 or n < debug else None
        view = row.get("view") or "side"
        band = int(round(float(row["dist"]))) if view in ("far", "lod") else "near"
        try:
            if view == "top":
                top, ratio = measure_top(row, src, dbg)
            else:
                slices, ratio, cmap = measure_side(row, src, dbg, row["kind"] == "bush" and band in MAP_BANDS)
        except Exception as e:  # one bad shot shouldn't stop the rest
            bad += 1
            log(f"foliage: {row['id']}: skipped ({e})")
            continue
        p = per_kind.setdefault(row["prefab"], dict(kind=row["kind"], heights=[], dists=[], top=None,
                                                    bands=collections.defaultdict(dict),
                                                    maps=collections.defaultdict(list)))
        if view == "top":
            p["top"] = top
            continue
        # distance band: "near" for the close-up sides, else the fixed distance in metres
        if band == "near":
            p["heights"].append(float(row["height"]))
            p["dists"].append(float(row["dist"]))
        if cmap is not None:
            p["maps"][band].append(cmap)
        for s in slices:
            lines.append([row["id"], row["prefab"], row["kind"], band, s["y"], s["cover"], s["k"], s["width"], s["px"]])
            if s["px"] > 0 or band == "near":
                p["bands"][band].setdefault(s["y"], []).append((s["cover"], s["k"], s["px"]))

    def summarise(sl):
        return [dict(y=y, cover=round(float(np.mean([c for c, _, _ in v])), 3),
                     k=round(float(np.mean([k for _, k, _ in v])), 3), n=len(v),
                     px=int(np.mean([x for _, _, x in v])))
                for y, v in sorted(sl.items())]

    profiles = {}
    for prefab, p in sorted(per_kind.items()):
        if not p["heights"]:
            continue
        near = summarise(p["bands"]["near"])
        bands = [dict(d=round(float(np.median(p["dists"])), 1), near=True, slices=near)]
        bands += [dict(d=d, slices=summarise(sl)) for d, sl in sorted((d, sl) for d, sl in p["bands"].items() if d != "near")]
        profiles[prefab] = dict(
            kind=p["kind"], shots=len(p["heights"]), height=round(float(np.median(p["heights"])), 2),
            slices=near, top=p["top"], bands=bands)
        for band, grids in p["maps"].items():
            # the sides' grids differ in size by a cell or two (each side's box): average where they overlap
            nj, nw = max(g.shape[0] for g in grids), max(g.shape[1] for g in grids)
            total, cnt = np.zeros((nj, nw)), np.zeros((nj, nw))
            for g in grids:
                pad = np.full((nj, nw), np.nan)
                off = (nw - g.shape[1]) // 2
                pad[:g.shape[0], off:off + g.shape[1]] = g
                good = ~np.isnan(pad)
                total[good] += pad[good]
                cnt[good] += 1
            grid = np.where(cnt > 0, total / np.maximum(cnt, 1), np.nan)
            cells = [[-1 if np.isnan(x) else int(round(x * 100)) for x in r] for r in grid]  # % blocked, -1 = unseen
            for entry in bands:
                if entry["d"] == band or (band == "near" and entry.get("near")):
                    entry["map"] = dict(cell=CELL, rows=cells)  # rows bottom to top, columns across, % blocked
    for d in [src, *out_dirs]:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "foliage_shots.csv"), "w", newline="", encoding="utf8") as f:
            wr = csv.writer(f)
            wr.writerow(["id", "prefab", "kind", "band", "slice_m", "cover", "k", "width_m", "pixels"])
            wr.writerows(lines)
        with open(os.path.join(d, "foliage_profiles.json"), "w", encoding="utf8") as f:
            json.dump(profiles, f, indent=1)
    cov = lambda kind: np.mean([s["cover"] for p in profiles.values() if p["kind"] == kind for s in p["slices"]] or [0])
    log(f"foliage: {len(profiles)} kinds measured from {len(rows)} views, {bad} skipped; "
        f"average cover inside the outline: trees {cov('tree'):.0%}, bushes {cov('bush'):.0%}")
    return profiles
