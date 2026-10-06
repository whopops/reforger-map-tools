"""Low-poly tree and bush models for the website's 3D view, fitted to the game's own meshes (no game run).

Not the game's models: for each species a few simple shapes of our own, placed and sized from the game mesh, so the
site ships no game geometry or textures.

  crown   points are sampled over the crown's leaf cards wherever the leaf texture is solid (alpha >= 0.5, as the game
          draws it; prefab material swaps such as the autumn variants applied, see foliage_mesh), clustered into a few
          clumps (k-means), and each clump becomes a 12-vertex hull (an icosahedron with one vertex straight up, each
          vertex pushed out to the clump's furthest point that way, stray points left out, so conifers keep their tip)
  trunk   a 6-sided tapered tube up the main stem, tracked through the bark vertices 0.5 m at a time
  far     a second, coarser version (a third of the clumps, a 4-sided trunk) for the 3D view's distant tiles

Checked against the real alpha-tested mesh from 8 sides, as silhouette IoU with the crown's outline closed over 0.4 m
gaps (what the eye reads as the tree's shape): spruce 3s 0.84, birch 2s 0.84, pine 3s 0.84, hazel 1 0.82; over all
species of the three maps median 0.79, lowest 0.53 (dead spruces, whose bare branches are left out).

Writes, beside a published map's trees/species.json (one model per species, in its order):
  trees/models.json     {format, version, verts, near, far, models: [{name, h, near: [first, count], far: [first,
                        count], iou}]}: vertex ranges into models.bin.gz; near / far the largest count of each, which
                        the page draws per instance
  trees/models.bin.gz   Int16 x, y, z, part per vertex, non-indexed triangles: x, y, z in cm at mesh scale 1 from the
                        plant's base (game axes: x east, y up, z north at yaw 0); part 0 trunk, 1-255 a crown clump
                        (its number is a shade variation)
The page scales a model by each tree's height (the trees/ tiles' height / the model's h) and turns it by its yaw.

    python -m rmtlib.tree_models <map folder of the site> [--out <folder>]   # e.g. arma-map/static/data/maps/everon
"""

import argparse
import concurrent.futures as cf
import gzip
import hashlib
import io
import json
import math
import os
import sys

import numpy as np

from . import foliage_mesh as fm
from . import prefab, xob

FORMAT = 1
DENSITY = 300.0       # samples per m^2 of leaf card
CAP = 60000           # most leaf points kept per species
CELL = 1.1            # metres of crown per clump (cube root of the crown's box volume / CELL clumps)
MAX_CLUMPS = 10
SPARSE = 0.1          # m^2 of solid leaf per m^3 of clump below which a clump is split (see clumps)
MOST_CLUMPS = 14      # ...up to this many in all
CLOSE = 0.4           # gaps in the real crown's outline closed for the IoU check (m)

# an icosahedron turned so vertex 0 points straight up
_t = (1 + 5 ** 0.5) / 2
_V = np.array([[-1, _t, 0], [1, _t, 0], [-1, -_t, 0], [1, -_t, 0], [0, -1, _t], [0, 1, _t], [0, -1, -_t], [0, 1, -_t],
               [_t, 0, -1], [_t, 0, 1], [-_t, 0, -1], [-_t, 0, 1]], float)
_V /= np.linalg.norm(_V, axis=1)[:, None]
ICO_F = np.array([[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2],
                  [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11],
                  [6, 2, 10], [8, 6, 7], [9, 8, 1]])


def _up(v):
    """Rotation taking v to +y."""
    a, b = v / np.linalg.norm(v), np.array([0.0, 1.0, 0.0])
    c, s = float(a @ b), np.cross(a, b)
    if np.linalg.norm(s) < 1e-9:
        return np.eye(3)
    k = np.array([[0, -s[2], s[1]], [s[2], 0, -s[0]], [-s[1], s[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


ICO_V = _V @ _up(_V[0]).T


def leaf_points(parts, rng):
    """Points on the crown cards where the leaf texture is solid, and the bark's vertices."""
    pts, bark = [], []
    for p in parts:
        op, _ = fm.material(p.material)
        if not op:
            bark.append(p.positions[p.triangles].reshape(-1, 3))
            continue
        tex = fm.opacity(op)
        img = tex[min(2, len(tex) - 1)]
        ih, iw = img.shape
        tri, uv = p.positions[p.triangles], p.uv[p.triangles]
        area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        idx = np.repeat(np.arange(len(tri)), rng.poisson(area * DENSITY))
        if not len(idx):
            continue
        a, b = rng.random(len(idx)), rng.random(len(idx))
        flip = a + b > 1
        a[flip], b[flip] = 1 - a[flip], 1 - b[flip]
        w = np.stack([1 - a - b, a, b], 1)
        P = (tri[idx] * w[:, :, None]).sum(1)
        U = (uv[idx] * w[:, :, None]).sum(1)
        keep = img[(U[:, 1] * ih).astype(int) % ih, (U[:, 0] * iw).astype(int) % iw] >= 128
        pts.append(P[keep])
    pts = np.concatenate(pts) if pts else np.zeros((0, 3))
    if len(pts) > CAP:
        pts = pts[rng.choice(len(pts), CAP, replace=False)]
    return pts, (np.concatenate(bark) if bark else np.zeros((0, 3)))


def _hull(q):
    """The 12-vertex hull around one cluster, or None."""
    if len(q) < 12:
        return None
    c = np.median(q, 0)
    d = np.linalg.norm(q - c, axis=1)
    q = q[d <= np.percentile(d, 98) * 1.25]              # a few stray points do not stretch a clump
    s = np.maximum((q - c) @ ICO_V.T, 0.0).max(0)
    return c + ICO_V * np.maximum(s, 0.15)[:, None], len(q)


def _volume(V):
    from scipy.spatial import ConvexHull
    try:
        return float(ConvexHull(V).volume)
    except Exception:
        return 0.0


def clumps(points, k, sparse=None, most=None):
    """Hulls of 12 vertices around k clusters of points: (vertices, faces) each. While there are fewer than `most`,
    the clump whose hull is most nearly air (fewer than `sparse` m^2 of solid leaf per m^3: the bare lower branches of
    a dead spruce) is split in two, so a thin crown does not become one big solid lump."""
    from scipy.cluster.vq import kmeans2
    sparse = SPARSE if sparse is None else sparse
    most = MOST_CLUMPS if most is None else most
    if len(points) < 20:
        return []
    k = max(1, min(k, len(points) // 40))
    _, lab = kmeans2(points, k, minit="++", seed=2, iter=30)
    out = []                                              # (leaf m^2 per m^3, points, vertices)
    for i in range(k):
        h = _hull(points[lab == i])
        if h is not None:
            out.append((h[1] / DENSITY / max(_volume(h[0]), 1e-6), points[lab == i], h[0]))
    while len(out) < most:
        j = min(range(len(out)), key=lambda i: out[i][0]) if out else None
        if j is None or out[j][0] >= sparse or len(out[j][1]) < 80:
            break
        _, q, _ = out.pop(j)
        _, sub = kmeans2(q, 2, minit="++", seed=3, iter=30)
        for i in range(2):
            h = _hull(q[sub == i])
            if h is not None:
                out.append((h[1] / DENSITY / max(_volume(h[0]), 1e-6), q[sub == i], h[0]))
    # bottom first, so the clump numbers (the shade variation) run up the plant
    return sorted([(V, ICO_F.copy()) for _, _, V in out], key=lambda m: m[0][:, 1].mean())


def trunk(bark, top, sides=6, segs=5):
    """A tapered tube up the main stem, or None (a bush, a plant without bark)."""
    if len(bark) < 30:
        return None
    lo = bark[bark[:, 1] < 0.6]
    if len(lo) < 5:
        return None
    c = np.median(lo[:, [0, 2]], 0)
    rings, y = [], 0.0
    while y < top:
        band = bark[(bark[:, 1] >= y) & (bark[:, 1] < y + 0.5)]
        if len(band):
            dist = np.linalg.norm(band[:, [0, 2]] - c, axis=1)
            near = band[dist < max(0.6, 3 * (rings[-1][2] if rings else 0.3))]
            if len(near) < 4:
                break
            step = np.median(near[:, [0, 2]], 0) - c
            if np.linalg.norm(step) > 0.15:                 # the stem leans; a branch jumps
                step *= 0.15 / np.linalg.norm(step)
            c = c + step
            r = float(np.median(np.linalg.norm(near[:, [0, 2]] - c, axis=1)))
            r = min(r, rings[-1][2] * 1.1) if rings else r
            if r < 0.02:
                break
            rings.append((c.copy(), y + 0.25, r))
        y += 0.5
    if len(rings) < 2:
        return None
    rings = [rings[i] for i in np.linspace(0, len(rings) - 1, min(segs + 1, len(rings))).round().astype(int)]
    rings[0] = (rings[0][0], 0.0, rings[0][2])
    V, F = [], []
    for c, y, r in rings:
        for a in range(sides):
            th = 2 * math.pi * (a + 0.5) / sides
            V.append([c[0] + r * math.cos(th), y, c[1] + r * math.sin(th)])
    for j in range(len(rings) - 1):
        for a in range(sides):
            i0, i1 = j * sides + a, j * sides + (a + 1) % sides
            F += [[i0, i1 + sides, i1], [i0, i0 + sides, i1 + sides]]
    return np.array(V), np.array(F)


def fit(prefab_path, score=True):
    """The near and far models of one prefab: dict(h, near, far, iou), each model a list of (vertices, faces, part)."""
    rng = np.random.default_rng(1)
    lods, _ = fm.mesh(prefab.resource(prefab_path, "Object"))
    parts = fm._swapped(lods, fm.material_swaps(prefab_path))[0].parts
    pts, bark = leaf_points(parts, rng)
    height = float(max(np.concatenate([p.positions for p in parts])[:, 1].max(), 0.1))
    span = np.ptp(pts, 0) if len(pts) > 1 else np.ptp(bark, 0) if len(bark) > 1 else np.ones(3)
    k = int(np.clip(round(float(np.prod(np.maximum(span, 0.1))) ** (1 / 3) / CELL), 2, MAX_CLUMPS))
    top = max(0.95 * height, 0.6)                       # up the stem until its bark runs out (bare dead trees)
    source = pts if len(pts) >= 20 else bark            # no leaves (a log, a dead tree): clumps of the bark
    if source is bark:                                  # long and thin: a clump per metre or so of its length
        k = int(np.clip(round(float(np.ptp(bark, 0).max()) / 1.2), 2, MAX_CLUMPS))
    out = {}
    for name, kk, sides, segs in (("near", k, 6, 6), ("far", max(1, round(k / 3)), 4, 3)):
        # the far model is not split further: it stays a handful of clumps
        model = [(V, F, i + 1) for i, (V, F) in enumerate(clumps(source, kk, most=None if name == "near" else kk))]
        tr = trunk(bark, top, sides, segs) if source is pts else None
        if tr is not None:
            model.append((tr[0], tr[1], 0))
        out[name] = model
    out["h"] = height
    out["iou"] = round(silhouette_iou(parts, out["near"], height), 3) if score else None
    return out


def silhouette_iou(parts, model, height, yaws=8):
    """The model's outline against the real alpha-tested mesh's, closed over CLOSE m gaps, from yaws sides (the photo
    job's close-up camera)."""
    from scipy import ndimage
    allp = np.concatenate([p.positions for p in parts])
    half = float(max(abs(allp[:, 0]).max(), abs(allp[:, 2]).max()))
    cam = fm.Camera(fm.close_up_distance(height, half), height, True)
    solid = [xob.Part(None, 0, V, np.zeros((len(V), 2)), F) for V, F, _ in model]
    r = max(1, int(round(CLOSE / (cam.dist / cam.f))))
    ious = []
    for y in range(yaws):
        a, b = fm.draw_view(parts, y * 360.0 / yaws, cam), fm.draw_view(solid, y * 360.0 / yaws, cam)
        ox, oy = min(a[3], b[3]), min(a[4], b[4])
        W = max(a[3] + a[0].shape[1], b[3] + b[0].shape[1]) - ox + 2 * r + 4
        H = max(a[4] + a[0].shape[0], b[4] + b[0].shape[0]) - oy + 2 * r + 4
        A, B = np.zeros((H, W), bool), np.zeros((H, W), bool)
        A[a[4] - oy + r + 2:a[4] - oy + r + 2 + a[0].shape[0], a[3] - ox + r + 2:a[3] - ox + r + 2 + a[0].shape[1]] = a[0]
        B[b[4] - oy + r + 2:b[4] - oy + r + 2 + b[0].shape[0], b[3] - ox + r + 2:b[3] - ox + r + 2 + b[0].shape[1]] = b[0]
        grown = ndimage.distance_transform_edt(~A) <= r                    # closing: grow by r, then shrink by r
        A = ndimage.binary_fill_holes(ndimage.distance_transform_edt(grown) > r)
        ious.append((A & B).sum() / max((A | B).sum(), 1))
    return float(np.mean(ious))


def _prefab_for(names):
    """Species name (the prefab's file name without .et, as trees/species.json has it) -> the base game prefab."""
    by = {}
    for p in fm.standing_prefabs():
        by.setdefault(os.path.basename(p)[:-3].lower(), p)
    return {n: by.get(n.lower()) for n in names}


def _fit(args):
    path, score = args
    try:
        return path, fit(path, score), None
    except Exception as e:  # one unreadable mesh leaves that species on the page's ring shape
        return path, None, f"{type(e).__name__}: {e}"


def write(map_dir, score=True, jobs=None, out_dir=None, log=print):
    """trees/models.json and models.bin.gz for a published map (see the module notes), into out_dir (default the
    map's trees/)."""
    with open(os.path.join(map_dir, "trees", "species.json"), encoding="utf8") as f:
        names = [s["name"] for s in json.load(f)["species"]]
    pref = _prefab_for(names)
    todo = sorted({p for p in pref.values() if p})
    fits = {}
    # one process unless asked: each process keeps its own copy of every mesh and texture it reads, so in parallel
    # the memory adds up (one process: under 0.5 GB, about 6 minutes for Everon)
    jobs = jobs or 1
    if jobs == 1:
        results = map(_fit, [(p, score) for p in todo])
        ex = None
    else:
        ex = cf.ProcessPoolExecutor(jobs)
        results = ex.map(_fit, [(p, score) for p in todo])
    try:
        for path, res, err in results:
            if err:
                log(f"tree models: {path}: {err}")
            else:
                fits[path] = res
    finally:
        if ex:
            ex.shutdown()
    verts, models = [], []
    for name in names:
        res = fits.get(pref[name])
        entry = dict(name=name, h=round(res["h"], 2) if res else 0, near=[0, 0], far=[0, 0],
                     iou=res["iou"] if res else None)
        if res:
            for lod in ("near", "far"):
                first = len(verts)
                for V, F, part in res[lod]:
                    for tri in F:
                        for i in tri:
                            x, y, z = V[i]
                            verts.append((round(x * 100), round(y * 100), round(z * 100), part))
                entry[lod] = [first, len(verts) - first]
        models.append(entry)
    arr = np.clip(np.array(verts, np.int64), -32768, 32767).astype("<i2") if verts else np.zeros((0, 4), "<i2")
    data = arr.tobytes()
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as g:
        g.write(data)
    out_dir = out_dir or os.path.join(map_dir, "trees")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "models.bin.gz"), "wb") as f:
        f.write(buf.getvalue())
    doc = dict(format=FORMAT, version=hashlib.sha1(data).hexdigest()[:12], verts=len(verts),
               near=max((m["near"][1] for m in models), default=0), far=max((m["far"][1] for m in models), default=0),
               note="made by reforger-map-tools rmtlib/tree_models.py; see there", models=models)
    with open(os.path.join(out_dir, "models.json"), "w", encoding="utf8") as f:
        json.dump(doc, f, separators=(",", ":"))
    missing = [m["name"] for m in models if not m["near"][1]]
    ious = [m["iou"] for m in models if m["iou"] is not None]
    log(f"tree models: {len(models) - len(missing)} of {len(models)} species, {len(verts) // 3:,} triangles, "
        f"{len(buf.getvalue()) / 1e3:.0f} KB; near up to {doc['near'] // 3} triangles, far up to {doc['far'] // 3}"
        + (f"; outline IoU median {np.median(ious):.2f}, lowest {min(ious):.2f}" if ious else "")
        + (f"; no model (ring shape kept): {', '.join(missing)}" if missing else ""))
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map_dir", help="a map's folder of the site, with trees/species.json")
    ap.add_argument("--no-score", action="store_true", help="skip the outline check (faster)")
    ap.add_argument("--jobs", type=int, default=1, help="processes (default 1; each needs about 0.5 GB or more)")
    ap.add_argument("--out", help="folder for the two files (default the map's trees/)")
    args = ap.parse_args(argv)
    write(args.map_dir, not args.no_score, args.jobs, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
