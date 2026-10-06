"""How see-through every tree and bush prefab is, measured from the game's own meshes and opacity textures (no game run).

Replaces photographing each plant (rmtlib/foliage.py) as the source of the per-kind numbers; the photographs stay as
the check. For each standing tree and bush prefab in the base game (and any prefab named), at mesh scale 1:

  * the mesh (.xob, rmtlib/xob.py) and each crown material's opacity map (.edds, rmtlib/edds.py) are read from the
    paks; trunks and other materials without an opacity map are opaque;
  * for each distance band (the close-up, then 25, 50, 100, 200, 300 m) the LOD the game draws there is picked
    (LOD_RULE below) and drawn orthographically, side on, from 8 yaws, at the pixel size a 2560x1440 picture with a
    40 degree lens has at that distance (the close-up: backed off until the plant fills 85% of the picture's height,
    as the photo job does), alpha-tested as the game does (opacity at the mip the game samples at that size, bilinear,
    >= ALPHA_REF; cards seen edge-on fade by the material's FadeFaces);
  * per 0.25 m slice of height: cover (blocked share between the outermost blocked columns, the photographs' metric),
    width_m, and three extinctions:
       k        -ln(1 - cover) / width: the slab value, kept because the field map rebuilds a slice's width from it
       k_disc   the k that, over a disc as wide as the slice (how bake_plants and the field map place a plant),
                lets through exactly as much as the slice does: the number the light grids use
       k_chord  -ln(transmittance through the crown) / mean distance from the first card to the last along a ray
                (the handoff plan's chord k), and k90 the 90th percentile of per-ray tau / chord
    with n (rays through the crown) and cover_sd (spread over the 8 yaws);
  * the crown from straight below (cover, width_m, k from the vertical chords), and for bushes the 0.25 m cell map of
    the close-up and the 25 m band (percent blocked, as foliage.py writes it).

Checked against the game (build 24903726, 2026-10-05, zero-wind photographs from the photo job with -rmtFoliageWind=0):
cover per slice MAE 0.022, correlation 0.975 over 15 kinds close up; 0.031 / 0.976 for 5 kinds from the close-up out to
200 m; per-kind MAE 0.020, correlation 0.988 on Everon's 70 photographed kinds (photographed in wind). The game's
alpha test for crowns (MatPBRTreeCrown leaves AlphaTest at 0; the shader's reference comes from the engine) behaves as
0.5. Video settings change what the game draws (Atoc, TextureDetail, GeometricDetail): the numbers are for the settings
the check ran with (no alpha-to-coverage, default object detail).

  python -m rmtlib.foliage_mesh build [--out <file>] [--only <regex>] [--jobs N]   the library for the base game
  python -m rmtlib.foliage_mesh show <resource>                                     one record, measured now
"""

import argparse
import functools
import gzip
import json
import math
import os
import re
import sys
import time
import zlib

import numpy as np

from . import edds, foliage, pak, prefab, xob

ALPHA_REF = 0.5
SLICE = foliage.SLICE
CELL = foliage.CELL
YAWS = 8
BANDS = (25, 50, 100, 200, 300)      # metres, as the photo job's FoliageLod default
FOV = 40.0                           # the photo job's lens (vertical, degrees) and picture height
SCREEN_H = 1440
EYE = 1.7                            # the camera's height above the plant's base, a standing player's eye
VIEW_X, VIEW_Y = 2000, 1600          # pixels from the centre drawn at most: more than any band reaches, a bound
PIXEL_ANGLE = 2 * math.tan(math.radians(FOV / 2)) / SCREEN_H   # metres per pixel per metre of distance
FORMAT = 1
METHOD = 2                           # raise when the measurement changes: every record is measured again
# The distance at which the game swaps LOD i for LOD i+1, fitted to 18 measured distances (10-320 m) on 9 kinds
# (2026-10-05, 2560x1440, 40 degrees, GeometricDetail 3): d = K * R^a * LODFactor_i^b * triangles_i^c, R the mesh's
# bounding radius (m), LODFactor_i the prefab MeshObject's LODFactors entry, triangles_i the LOD's count. Leave-one-kind-
# out error 11%. Where a prefab has no LODFactors the LODs are given to the bands in their authored order instead.
LOD_RULE = dict(K=1963.368, a=1.088, b=-0.395, c=-0.502, fov=FOV, screen_h=SCREEN_H, fitted="2026-10-05")


# ------------------------------------------------------------------------------------------------ game files
@functools.lru_cache(maxsize=None)
def _rdb_guids():
    """Resource path -> GUID for every vegetation prefab, mesh and texture in the base game (resourceDatabase.rdb)."""
    from .steam import GAME_APP, app
    game, _ = app(GAME_APP)
    out = {}
    rx = re.compile(rb"([A-Za-z0-9_\-./ ]+\.(?:et|xob|edds|emat))\x00")
    for name in ("core", "data"):
        path = os.path.join(game, "addons", name, "resourceDatabase.rdb")
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        for m in rx.finditer(data):
            g = data[m.end() + 6:m.end() + 14]
            if len(g) == 8:
                out.setdefault(m.group(1).decode("ascii", "replace"), g[::-1].hex().upper())
    return out


def resource_name(path):
    g = _rdb_guids().get(path)
    return "{%s}%s" % (g, path) if g else path


def standing_prefabs():
    """Every standing tree and bush prefab in the base game that has a mesh."""
    out = []
    for p in prefab._index():
        if p.endswith(".et") and p.startswith("Prefabs/Vegetation/") and foliage.standing_plant("/" + p):
            if prefab.resource(p, "Object"):
                out.append(p)
    return sorted(out)


def _bytes(path):
    return pak.read(*prefab._index()[path])


def _fingerprint(path):
    e = prefab._index()[path]
    return {"path": path, "size": e[3], "crc32": "%08x" % (zlib.crc32(_bytes(path)) & 0xFFFFFFFF)}


def material_value(path, name, rx=r"(\S.*)"):
    for p in prefab.chain(path):
        try:
            m = re.search(r"^\s*" + name + r"\s+" + rx + r"\s*$", prefab.text(p), re.M)
        except FileNotFoundError:
            continue
        if m:
            return m.group(1)
    return None


@functools.lru_cache(maxsize=None)
def material(path):
    """(opacity map path or None, FadeFaces or 0) of an .emat."""
    if not path:
        return None, 0.0
    op = material_value(path, "OpacityMap", r'"\{[0-9A-F]+\}([^"]+)"')
    fade = material_value(path, "FadeFaces", r"([-0-9.eE]+)")
    return op, float(fade) if fade else 0.0


@functools.lru_cache(maxsize=16)
def opacity(path):
    return edds.mips(_bytes(path))


@functools.lru_cache(maxsize=None)
def mesh(path):
    return xob.parse(_bytes(path))


def material_swaps(prefab_path):
    """The prefab's MeshObject `Materials` (MaterialAssignClass: SourceMaterial -> AssignedMaterial), nearest prefab
    winning: the autumn and other variants keep the mesh and swap the leaf materials this way."""
    out = {}
    rx = re.compile(r'SourceMaterial\s+"([^"]+)"\s*AssignedMaterial\s+"(?:\{[0-9A-F]+\})?([^"]+)"')
    for p in reversed(prefab.chain(prefab_path)):
        try:
            out.update(rx.findall(prefab.text(p)))
        except FileNotFoundError:
            continue
    return out


def _swapped(lods, swaps):
    """The LODs with the prefab's material swaps applied (copies; the cached mesh is left alone)."""
    if not swaps:
        return lods
    def mat(m):
        return swaps.get(os.path.splitext(os.path.basename(m))[0], m) if m else m
    return [xob.Lod(l.threshold, [xob.Part(mat(p.material), p.format, p.positions, p.uv, p.triangles)
                                  for p in l.parts]) for l in lods]


def _prefab_fingerprint(prefab_path):
    """CRC-32 of the prefab and its ancestors: a changed material swap, scale or LODFactors measures it again."""
    crc = 0
    for p in prefab.chain(prefab_path):
        try:
            crc = zlib.crc32(prefab.text(p).encode("utf8"), crc)
        except FileNotFoundError:
            continue
    return "%08x" % (crc & 0xFFFFFFFF)


def lod_factors(prefab_path):
    for p in prefab.chain(prefab_path):
        try:
            m = re.search(r"LODFactors\s*\{\s*([^}]*)\}", prefab.text(p))
        except FileNotFoundError:
            continue
        if m:
            return [float(x) for x in m.group(1).split()]
    return None


def switch_distances(lods, factors):
    """Where the game swaps each LOD for the next (m), or None when the rule cannot be applied."""
    if not factors or len(factors) < len(lods) - 1:
        return None
    pts = np.concatenate([p.positions for l in lods for p in l.parts])
    R = float(np.linalg.norm(pts.max(0) - pts.min(0)) / 2)
    r = LOD_RULE
    return [r["K"] * R ** r["a"] * max(factors[i], 1e-3) ** r["b"] * max(lods[i].triangles, 1) ** r["c"]
            for i in range(len(lods) - 1)]


def lod_for(d, switches, n):
    if switches is None:
        return None
    for i, s in enumerate(switches):
        if d < s:
            return i
    return n - 1


# ------------------------------------------------------------------------------------------------ drawing
def draw(parts, yaw, px, view="side"):
    """The parts turned by yaw (degrees, about the vertical) and drawn orthographically with px metres per pixel.
    view "side": looking along +z (columns x, rows y up); "top": looking up from below (columns x, rows z).
    Returns (blocked bool image, first-card depth, last-card depth, x0, y0) with row 0 at the top for "side"."""
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    P = [p.positions @ R.T for p in parts]
    allp = np.concatenate(P)
    if view == "side":
        X, Y, Z = 0, 1, 2
    else:
        X, Y, Z = 0, 2, 1
    x0, x1 = allp[:, X].min() - 2 * px, allp[:, X].max() + 2 * px
    y0, y1 = allp[:, Y].min() - 2 * px, allp[:, Y].max() + 2 * px
    W, H = int(math.ceil((x1 - x0) / px)) + 1, int(math.ceil((y1 - y0) / px)) + 1
    blocked = np.zeros((H, W), bool)
    zmin = np.full((H, W), np.inf)
    zmax = np.full((H, W), -np.inf)
    view_dir = np.array([0.0, 0.0, 1.0]) if view == "side" else np.array([0.0, 1.0, 0.0])
    for part, pos in zip(parts, P):
        op, fade = material(part.material)
        tex = opacity(op) if op else None
        sx = (pos[:, X] - x0) / px
        sy = (y1 - pos[:, Y]) / px if view == "side" else (pos[:, Y] - y0) / px
        sz = pos[:, Z]
        for t in part.triangles:
            xs, ys, zs = sx[t], sy[t], sz[t]
            xa, xb = max(0, int(math.floor(xs.min()))), min(W, int(math.ceil(xs.max())) + 1)
            ya, yb = max(0, int(math.floor(ys.min()))), min(H, int(math.ceil(ys.max())) + 1)
            if xb <= xa or yb <= ya:
                continue
            d = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(d) < 1e-12:
                continue
            gx, gy = np.meshgrid(np.arange(xa, xb) + 0.5, np.arange(ya, yb) + 0.5)
            l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / d
            l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / d
            l2 = 1 - l0 - l1
            m = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            if not m.any():
                continue
            z = l0 * zs[0] + l1 * zs[1] + l2 * zs[2]
            sl = (slice(ya, yb), slice(xa, xb))
            np.minimum(zmin[sl], np.where(m, z, np.inf), out=zmin[sl])
            np.maximum(zmax[sl], np.where(m, z, -np.inf), out=zmax[sl])
            if tex is None:
                blocked[sl] |= m
                continue
            U = part.uv[t]
            u = l0 * U[0, 0] + l1 * U[1, 0] + l2 * U[2, 0]
            v = l0 * U[0, 1] + l1 * U[1, 1] + l2 * U[2, 1]
            th, tw = tex[0].shape
            ta = abs((U[1, 0] - U[0, 0]) * (U[2, 1] - U[0, 1]) - (U[2, 0] - U[0, 0]) * (U[1, 1] - U[0, 1])) * tw * th
            lvl = 0.5 * math.log2(ta / abs(d)) if ta > 0 else 0
            img = tex[int(min(max(round(lvl), 0), len(tex) - 1))]
            ih, iw = img.shape
            fx, fy = (u * iw - 0.5) % iw, (v * ih - 0.5) % ih
            ix, iy = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
            ax, ay = fx - ix, fy - iy
            jx, jy = (ix + 1) % iw, (iy + 1) % ih
            alpha = (img[iy, ix] * (1 - ax) * (1 - ay) + img[iy, jx] * ax * (1 - ay)
                     + img[jy, ix] * (1 - ax) * ay + img[jy, jx] * ax * ay) / 255.0
            if fade > 0:
                tri = pos[t]
                n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                cos = abs(n @ view_dir) / max(np.linalg.norm(n), 1e-12)
                alpha = alpha * min(1.0, cos / fade)
            blocked[sl] |= m & (alpha >= ALPHA_REF)
    return blocked, zmin, zmax, x0, y1 if view == "side" else y0


# ------------------------------------------------------------------------------------------------ measuring
def k_disc(T, half):
    """The k for which a disc of radius `half` (m), with e^(-k * chord) through it, passes on average what the slice's
    columns do (T: transmittance of each column, evenly spread across the slice's width). 0 for a clear slice."""
    T = np.asarray(T, np.float64)
    if not len(T) or half <= 0:
        return 0.0
    target = float(T.mean())
    if target >= 0.999:
        return 0.0
    target = max(target, 0.01)       # as the slab value caps cover at 0.99: a fully blocked slice is not infinitely dense
    b = (np.arange(len(T)) + 0.5) / len(T) * 2 - 1          # offsets across the disc, -1..1
    L = 2 * half * np.sqrt(np.clip(1 - b * b, 0, 1))
    lo, hi = 0.0, 1.0
    while np.exp(-hi * L).mean() > target and hi < 1e4:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if np.exp(-mid * L).mean() > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def slice_numbers(blocked, zmin, zmax, px):
    """One slice (rows of the side view between two heights): the numbers the library keeps, or None if empty."""
    cols = np.nonzero(blocked.any(axis=0))[0]
    if not len(cols):
        return None
    c0, c1 = cols[0], cols[-1] + 1
    b = blocked[:, c0:c1]
    cover = float(b.mean())
    width = (c1 - c0) * px
    k = -math.log(max(1e-3, 1 - min(cover, 0.999))) / max(width, SLICE)
    T = 1 - b.mean(axis=0)
    hit = np.isfinite(zmin[:, c0:c1])
    chord = np.where(hit, zmax[:, c0:c1] - zmin[:, c0:c1], np.nan)
    crown = hit.any(axis=0)
    out = dict(cover=cover, width=width, k=k, k_disc=k_disc(T, width / 2), n=int(crown.sum()))
    if crown.any():
        ch = np.nanmean(chord[:, crown], axis=0)
        ch = np.maximum(ch, px)
        Tc = T[crown]
        out["k_chord"] = -math.log(max(float(Tc.mean()), 1e-3)) / float(ch.mean())
        out["k90"] = float(np.percentile(-np.log(np.maximum(Tc, 1e-3)) / ch, 90))
    else:
        out["k_chord"] = out["k90"] = 0.0
    return out


class Camera:
    """The photo job's camera (RMT_FoliageCapture.PlaceCamera): `dist` metres south of the plant's axis, at a standing
    eye's height above its base, looking north, pitched to the plant (the close-up: halfway between its top and base;
    a distance band: at half its height), 40 degree lens, 1440 pixels high."""

    def __init__(self, dist, height, near, eye=EYE):
        self.pos = np.array([0.0, eye, -dist])
        aim = (math.atan2(height - eye, dist) + math.atan2(-eye, dist)) / 2 if near else math.atan2(height * 0.5 - eye, dist)
        self.fwd = np.array([0.0, math.sin(aim), math.cos(aim)])
        self.right = np.array([1.0, 0.0, 0.0])
        self.up = np.cross(self.fwd, self.right)
        self.f = (SCREEN_H / 2) / math.tan(math.radians(FOV / 2))
        self.dist = dist

    def project(self, pts):
        rel = np.asarray(pts, np.float64) - self.pos
        z = rel @ self.fwd
        return self.f * (rel @ self.right) / z, -self.f * (rel @ self.up) / z, z


def draw_view(parts, yaw, cam):
    """The parts turned by yaw (degrees, about the vertical) seen through cam. Returns (blocked, first-card depth,
    last-card depth, ox, oy): images cropped to the plant, pixel (r, c) at screen (oy + r, ox + c) from the centre."""
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    P = [p.positions @ R.T for p in parts]
    proj = [cam.project(p) for p in P]
    # the canvas: what is in front of the camera, within the photo's frame and a margin (a vertex just in front of
    # the lens projects thousands of screens away; sizing the canvas by it once asked for 112 GiB)
    front = np.concatenate([q[2] for q in proj]) > 0.05
    allx = np.clip(np.concatenate([q[0] for q in proj])[front], -VIEW_X, VIEW_X)
    ally = np.clip(np.concatenate([q[1] for q in proj])[front], -VIEW_Y, VIEW_Y)
    if not len(allx):
        allx = ally = np.zeros(1)
    ox, oy = int(math.floor(allx.min())) - 2, int(math.floor(ally.min())) - 2
    W, H = int(math.ceil(allx.max())) - ox + 3, int(math.ceil(ally.max())) - oy + 3
    blocked = np.zeros((H, W), bool)
    zmin = np.full((H, W), np.inf)
    zmax = np.full((H, W), -np.inf)
    for part, pos, (px_, py_, pz) in zip(parts, P, proj):
        op, fade = material(part.material)
        tex = opacity(op) if op else None
        sx, sy = px_ - ox, py_ - oy
        for t in part.triangles:
            xs, ys, zs = sx[t], sy[t], pz[t]
            if (zs <= 0.05).any():
                continue
            xa, xb = max(0, int(math.floor(xs.min()))), min(W, int(math.ceil(xs.max())) + 1)
            ya, yb = max(0, int(math.floor(ys.min()))), min(H, int(math.ceil(ys.max())) + 1)
            if xb <= xa or yb <= ya:
                continue
            d = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(d) < 1e-12:
                continue
            gx, gy = np.meshgrid(np.arange(xa, xb) + 0.5, np.arange(ya, yb) + 0.5)
            l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / d
            l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / d
            l2 = 1 - l0 - l1
            m = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            if not m.any():
                continue
            iz = 1.0 / zs
            w0, w1, w2 = l0 * iz[0], l1 * iz[1], l2 * iz[2]
            ws = w0 + w1 + w2
            z = 1.0 / ws                                   # depth along the view, perspective-correct
            sl = (slice(ya, yb), slice(xa, xb))
            np.minimum(zmin[sl], np.where(m, z, np.inf), out=zmin[sl])
            np.maximum(zmax[sl], np.where(m, z, -np.inf), out=zmax[sl])
            if tex is None:
                blocked[sl] |= m
                continue
            U = part.uv[t]
            u = (w0 * U[0, 0] + w1 * U[1, 0] + w2 * U[2, 0]) / ws
            v = (w0 * U[0, 1] + w1 * U[1, 1] + w2 * U[2, 1]) / ws
            th, tw = tex[0].shape
            ta = abs((U[1, 0] - U[0, 0]) * (U[2, 1] - U[0, 1]) - (U[2, 0] - U[0, 0]) * (U[1, 1] - U[0, 1])) * tw * th
            lvl = 0.5 * math.log2(ta / abs(d)) if ta > 0 else 0
            img = tex[int(min(max(round(lvl), 0), len(tex) - 1))]
            ih, iw = img.shape
            fx, fy = (u * iw - 0.5) % iw, (v * ih - 0.5) % ih
            ix, iy = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
            ax, ay = fx - ix, fy - iy
            jx, jy = (ix + 1) % iw, (iy + 1) % ih
            alpha = (img[iy, ix] * (1 - ax) * (1 - ay) + img[iy, jx] * ax * (1 - ay)
                     + img[jy, ix] * (1 - ax) * ay + img[jy, jx] * ax * ay) / 255.0
            if fade > 0:
                tri = pos[t]
                n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                to_cam = cam.pos - tri.mean(0)
                cos = abs(n @ to_cam) / max(np.linalg.norm(n) * np.linalg.norm(to_cam), 1e-12)
                alpha = alpha * min(1.0, cos / fade)
            blocked[sl] |= m & (alpha >= ALPHA_REF)
    return blocked, zmin, zmax, ox, oy


def side_slices(parts, yaw, cam, height):
    """Per 0.25 m slice (by height above the base, measured at the plant's axis, as the photographs are): the slice
    numbers. Also returns the view for cell maps."""
    blocked, zmin, zmax, ox, oy = draw_view(parts, yaw, cam)
    rows = blocked.shape[0]
    px = cam.dist / cam.f                                  # metres per pixel at the plant's axis
    out = {}
    for j in range(int(math.ceil(height / SLICE))):
        y0, y1 = j * SLICE, min((j + 1) * SLICE, height)
        _, v, _ = cam.project([[0, y0, 0], [0, y1, 0]])
        r0, r1 = int(max(0, math.floor(v.min() - oy))), int(min(rows, math.ceil(v.max() - oy)))
        if r1 - r0 < foliage.MIN_ROWS:
            continue
        s = slice_numbers(blocked[r0:r1], zmin[r0:r1], zmax[r0:r1], px)
        out[round(y0, 2)] = s or dict(cover=0.0, width=0.0, k=0.0, k_disc=0.0, k_chord=0.0, k90=0.0, n=0)
    return out, (blocked, ox, oy)


def cell_map(images, cam, half, height):
    """foliage.cell_map's grid (rows from the base up, 2n columns across from the plant's axis, % blocked) averaged
    over the yaws' side views."""
    n, nj = max(1, int(math.ceil(half / CELL))), max(1, int(math.ceil(height / CELL)))
    total, count = np.zeros((nj, 2 * n)), np.zeros((nj, 2 * n))
    for blocked, ox, oy in images:
        H, W = blocked.shape
        ii = np.zeros((H + 1, W + 1))
        ii[1:, 1:] = blocked.astype(np.float64).cumsum(0).cumsum(1)
        for j in range(nj):
            for i in range(2 * n):
                u, v, _ = cam.project([[(i - n) * CELL, j * CELL, 0], [(i + 1 - n) * CELL, (j + 1) * CELL, 0]])
                ca, cb = int(round(u.min() - ox)), int(round(u.max() - ox))
                ra, rb = int(round(v.min() - oy)), int(round(v.max() - oy))
                ra2, rb2, ca2, cb2 = max(ra, 0), min(rb, H), max(ca, 0), min(cb, W)
                count[j, i] += 1
                if rb2 <= ra2 or cb2 <= ca2:
                    continue
                total[j, i] += (ii[rb2, cb2] - ii[ra2, cb2] - ii[rb2, ca2] + ii[ra2, ca2]) / max((rb - ra) * (cb - ca), 1)
    grid = total / np.maximum(count, 1)
    return dict(cell=CELL, rows=[[int(round(x * 100)) for x in r] for r in grid])


def top_view(parts, px):
    blocked, zmin, zmax, x0, y0 = draw(parts, 0, px, view="top")
    ys, xs = np.nonzero(blocked)
    if not len(xs):
        return dict(cover=0.0, width_m=0.0, k=0.0)
    cx, cy = (-x0) / px, (-y0) / px                          # the plant's axis
    r = np.hypot(xs - cx, ys - cy)
    radius = max(2.0, float(np.percentile(r, 95)))
    yy, xx = np.mgrid[0:blocked.shape[0], 0:blocked.shape[1]]
    disc = np.hypot(xx - cx, yy - cy) <= radius
    cover = float(blocked[disc].mean())
    hit = np.isfinite(zmin) & disc
    chord = float(np.mean(np.maximum(zmax[hit] - zmin[hit], px))) if hit.any() else px
    return dict(cover=round(cover, 4), width_m=round(2 * radius * px, 2),
                k=round(-math.log(max(1e-3, 1 - min(cover, 0.999))) / chord, 4))


def close_up_distance(height, half, eye=1.7):
    """How far the photo job's camera backs off for the close-up (RMT_FoliageCapture.PlaceCamera): from the plant's
    half-width + 1 m (at least 3 m), 12% further each try until the plant spans under 85% of the picture's height and
    width (a 4:3 frame at least), the camera at a standing eye's height."""
    v_half = math.radians(FOV / 2)
    h_half = math.atan(math.tan(v_half) * 1.33)
    dist = max(3.0, half + 1)
    for _ in range(40):
        top, base = math.atan2(height - eye, dist), math.atan2(-eye, dist)
        side = math.atan2(half, dist - half)
        if top - base < v_half * 2 * 0.85 and side < h_half * 0.85:
            break
        dist *= 1.12
    return dist


def record(prefab_path, yaws=YAWS):
    """Measure one prefab. The record is what the library stores for it (see the module notes)."""
    mesh_path = prefab.resource(prefab_path, "Object")
    lods, mats = mesh(mesh_path)
    swaps = material_swaps(prefab_path)
    lods = _swapped(lods, swaps)
    kind = "tree" if "/Vegetation/Tree/" in "/" + prefab_path else "bush"
    pts0 = np.concatenate([p.positions for p in lods[0].parts])
    height = float(max(pts0[:, 1].max(), SLICE))
    allp = np.concatenate([p.positions for l in lods for p in l.parts])
    half = float(max(abs(allp[:, 0]).max(), abs(allp[:, 2]).max()))
    factors = lod_factors(prefab_path)
    switches = switch_distances(lods, factors)
    d_near = close_up_distance(height, half)
    bands = [("near", d_near, 0)]
    for i, d in enumerate(BANDS):
        lod = lod_for(d, switches, len(lods))
        if lod is None:
            lod = min(i + 1, len(lods) - 1)            # no rule: the LODs in their authored order
        bands.append((d, d, lod))
    out_bands = []
    for name, d, lod in bands:
        cam = Camera(d, height, name == "near")
        px = d / cam.f
        per_yaw, images = [], []
        for y in range(yaws):
            s, img = side_slices(lods[lod].parts, y * 360.0 / yaws, cam, height)
            per_yaw.append(s)
            images.append(img)
        slices = []
        for ykey in sorted({k for s in per_yaw for k in s}):
            vals = [s[ykey] for s in per_yaw if ykey in s]
            mean = lambda f: float(np.mean([v[f] for v in vals]))
            slices.append(dict(y=ykey, cover=round(mean("cover"), 4), cover_sd=round(float(np.std([v["cover"] for v in vals])), 4),
                               k=round(mean("k"), 4), k_disc=round(mean("k_disc"), 4), k_chord=round(mean("k_chord"), 4),
                               k90=round(mean("k90"), 4), width_m=round(mean("width"), 3), n=int(sum(v["n"] for v in vals))))
        band = dict(d=round(d, 1), lod=lod, px=round(px, 4), slices=slices)
        if name == "near":
            band["near"] = True
        if kind == "bush" and name in foliage.MAP_BANDS:
            band["map"] = cell_map(images, cam, half, height)
        out_bands.append(band)
    textures = sorted({material(p.material)[0] for l in lods for p in l.parts if material(p.material)[0]})
    return dict(kind=kind, mesh=_fingerprint(mesh_path), textures=[_fingerprint(t) for t in textures],
                prefab=_prefab_fingerprint(prefab_path), materialSwaps=swaps or None,
                lodFactors=factors, lods=[dict(triangles=l.triangles, threshold=round(l.threshold, 4)) for l in lods],
                switch_m=[round(s, 1) for s in switches] if switches else None,
                lodRule="fitted" if switches else "authored order (no LODFactors)",
                prefabScale=prefab.number(prefab_path, "scale") or 1.0,
                height=round(height, 2), shots=yaws, top=top_view(lods[0].parts, max(d_near * PIXEL_ANGLE, 0.001)),
                bands=out_bands)


def _measure(path):
    try:
        return path, record(path), None
    except Exception as e:  # one unreadable mesh does not stop the library; it is listed as failed
        return path, None, f"{type(e).__name__}: {e}"


def build(out, only=None, jobs=None, log=print):
    """The library for every standing tree and bush prefab of the base game: <out> (.json.gz)."""
    from .steam import GAME_APP, app
    _, game_build = app(GAME_APP)
    paths = [p for p in standing_prefabs() if not only or re.search(only, p)]
    old = {}
    if os.path.isfile(out):
        with gzip.open(out, "rt", encoding="utf8") as f:
            prev = json.load(f)
        if prev.get("format") == FORMAT and prev.get("method") == METHOD:
            old = prev.get("records", {})
    recs, failed, todo = {}, {}, []
    for p in paths:
        name = resource_name(p)
        r = old.get(name)
        # unchanged prefab, mesh and textures: keep the old measurement (a game update rebuilds only what changed).
        # A record from before prefabs were fingerprinted is kept only for a prefab that swaps no materials (those
        # were measured with the mesh's own materials).
        fp = _prefab_fingerprint(p)
        same_prefab = r and (r.get("prefab") == fp or ("prefab" not in r and not material_swaps(p)))
        if same_prefab and r["mesh"] == _fingerprint(prefab.resource(p, "Object")) and \
                all(t == _fingerprint(t["path"]) for t in r["textures"]):
            recs[name] = dict(r, prefab=fp)
        else:
            todo.append(p)
    log(f"foliage library: {len(paths)} prefabs, {len(recs)} unchanged, {len(todo)} to measure")
    t0 = time.time()
    if jobs and jobs > 1 and len(todo) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(jobs) as ex:
            results = ex.map(_measure, todo)
            for i, (p, r, err) in enumerate(results):
                _keep(p, r, err, recs, failed, log, i, len(todo), t0)
    else:
        for i, p in enumerate(todo):
            _keep(*_measure(p), recs, failed, log, i, len(todo), t0)
    doc = dict(format=FORMAT, method=METHOD, gameBuild=game_build, made=time.strftime("%Y-%m-%dT%H:%M:%S"), alphaRef=ALPHA_REF,
               slice=SLICE, yaws=YAWS, bands=list(BANDS), lodRule=LOD_RULE, records=recs, failed=failed)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with gzip.open(out + ".part", "wt", encoding="utf8") as f:
        json.dump(doc, f, separators=(",", ":"))
    os.replace(out + ".part", out)
    log(f"foliage library: {len(recs)} records, {len(failed)} failed, {os.path.getsize(out) / 1e6:.2f} MB -> {out}")
    return doc


def _keep(p, r, err, recs, failed, log, i, n, t0):
    name = resource_name(p)
    if r is None:
        failed[name] = err
        log(f"  {p}: FAILED {err}")
    else:
        recs[name] = r
    if (i + 1) % 10 == 0 or i + 1 == n:
        log(f"  {i + 1}/{n} measured ({time.time() - t0:.0f} s)")


def load(path):
    with gzip.open(path, "rt", encoding="utf8") as f:
        return json.load(f)


def write_site(library, prefabs, out_dirs, log=print):
    """foliage_shots.csv and foliage_profiles.json (the files bake_plants and the field map read) for the given
    prefabs (resource names) from the library. Returns the prefabs it has no record for."""
    import csv
    recs = library["records"]
    by_path = {k.split("}", 1)[-1]: k for k in recs}
    profiles, lines, missing = {}, [], []
    for p in prefabs:
        key = p if p in recs else by_path.get(p.split("}", 1)[-1])
        if not key:
            missing.append(p)
            continue
        r = recs[key]
        bands = []
        for b in r["bands"]:
            # only what the field map (los-worker.js) reads; widths, cell maps and the other k's stay in the library
            # (and foliage_shots.csv, which the bakers read). Rounded as the photographs' files were.
            entry = dict(d=b["d"], slices=[dict(y=s["y"], cover=round(s["cover"], 3), k=round(s["k"], 3))
                                           for s in b["slices"]])
            if b.get("near"):
                entry["near"] = True
            bands.append(entry)
            band = "near" if b.get("near") else int(b["d"])
            for s in b["slices"]:
                lines.append([f"lib_{key.split('/')[-1].rsplit('.', 1)[0]}", p, r["kind"], band, s["y"], s["cover"],
                              s["k_disc"], s["width_m"], s["n"]])
        near = next(b for b in bands if b.get("near"))
        profiles[p] = dict(kind=r["kind"], shots=r["shots"], height=r["height"], slices=near["slices"], top=r["top"],
                           bands=bands, source="mesh library", gameBuild=library["gameBuild"])
    for d in out_dirs:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "foliage_shots.csv"), "w", newline="", encoding="utf8") as f:
            w = csv.writer(f)
            w.writerow(["id", "prefab", "kind", "band", "slice_m", "cover", "k", "width_m", "pixels"])
            w.writerows(lines)
        with open(os.path.join(d, "foliage_profiles.json"), "w", encoding="utf8") as f:
            json.dump(profiles, f, separators=(",", ":"))
    log(f"foliage: {len(profiles)} kinds from the mesh library ({library['gameBuild']}), {len(missing)} not in it")
    return missing


def library_path(game_build):
    from . import paths
    return os.path.join(paths.workspace(), "foliage-library", f"{game_build}.json.gz")


def site(raw, site_foliage, game_build, photos=None, log=print):
    """The map's foliage files (site/foliage/foliage_shots.csv and foliage_profiles.json) from the mesh library for
    this game build, for every standing plant kind in the map's entities export. Kinds the library has no record for
    (a mod's prefab, or a mesh that failed to read) come from the photographs in `photos` when there are any, else they
    are listed and left out. Returns False when there is no library for this build."""
    import csv
    import tempfile
    lib_file = library_path(game_build)
    if not os.path.isfile(lib_file):
        return False
    library = load(lib_file)
    with tempfile.TemporaryDirectory() as tmp:
        listed = os.path.join(tmp, "plants.csv")
        foliage.plant_list(raw, listed)
        with open(listed, encoding="utf8", newline="") as f:
            kinds = [r["prefab"] for r in csv.DictReader(f)]
    missing = write_site(library, kinds, [site_foliage], log)
    if missing and photos and os.path.isfile(os.path.join(photos, "shots.csv")):
        with tempfile.TemporaryDirectory() as tmp:
            measured = foliage.analyse(photos, [tmp], log=log)
            _merge_photos(site_foliage, tmp, [m for m in missing if m in measured])
            got = [m for m in missing if m in measured]
            log(f"foliage: {len(got)} kinds not in the library taken from the photographs")
            missing = [m for m in missing if m not in measured]
    if missing:
        log(f"foliage: {len(missing)} kinds have no measurement (photograph them: the foliage job with "
            f"--set FoliageLimit or a plants.csv of just these): " + ", ".join(m.split("/")[-1] for m in missing[:10]))
    return True


def _merge_photos(site_foliage, photo_dir, prefabs):
    import csv
    with open(os.path.join(site_foliage, "foliage_profiles.json"), encoding="utf8") as f:
        prof = json.load(f)
    with open(os.path.join(photo_dir, "foliage_profiles.json"), encoding="utf8") as f:
        extra = json.load(f)
    for p in prefabs:
        prof[p] = dict(extra[p], source="photographs")
    with open(os.path.join(site_foliage, "foliage_profiles.json"), "w", encoding="utf8") as f:
        json.dump(prof, f, separators=(",", ":"))
    keep = set(prefabs)
    with open(os.path.join(photo_dir, "foliage_shots.csv"), encoding="utf8", newline="") as f:
        rows = [r for r in csv.reader(f)][1:]
    with open(os.path.join(site_foliage, "foliage_shots.csv"), "a", encoding="utf8", newline="") as f:
        csv.writer(f).writerows(r for r in rows if r[1] in keep)


def site_option(map_dir, out_dir, game_build=None, log=print):
    """The mesh library's version of a published field map's foliage, beside the photographs' one, so the two can be
    compared on the site. `map_dir` is a map's folder of the site (with foliage/foliage_profiles.json, foliage.json,
    plants/ and los/index.json); `out_dir` gets the same four foliage files from the library:

        foliage/foliage_profiles.json  foliage.json  plants/<tx>_<tz>.bin.gz  light/foliage.bin.gz

    The plants (where each one stands, its kind and scale) are read back from the map's own plants/ tiles, so no
    entities export is needed; only the measurements change. Kinds the library has no record for keep their
    photograph numbers. The kinds keep the map's order, so the other files of the map (trees/, the rest of light/)
    still go with these."""
    import shutil
    from . import bake_plants
    lib_file = library_path(game_build) if game_build else max(
        (os.path.join(os.path.dirname(library_path("x")), f) for f in os.listdir(os.path.dirname(library_path("x")))
         if f.endswith(".json.gz")), key=os.path.getmtime)
    library = load(lib_file)
    with open(os.path.join(map_dir, "foliage", "foliage_profiles.json"), encoding="utf8") as f:
        photo_prof = json.load(f)
    with open(os.path.join(map_dir, "foliage.json"), encoding="utf8") as f:
        photo_doc = json.load(f)
    with open(os.path.join(map_dir, "los", "index.json"), encoding="utf8") as f:
        index = json.load(f)
    prefabs = photo_doc["prefabs"]
    if sorted(photo_prof) != prefabs:
        raise SystemExit(f"{map_dir}: foliage.json and foliage_profiles.json list different kinds")

    fol = os.path.join(out_dir, "foliage")
    missing = set(write_site(library, prefabs, [fol], log))
    with open(os.path.join(fol, "foliage_profiles.json"), encoding="utf8") as f:
        prof_json = json.load(f)
    for p in missing:
        prof_json[p] = dict(photo_prof[p], source="photographs")
    with open(os.path.join(fol, "foliage_profiles.json"), "w", encoding="utf8") as f:
        json.dump({p: prof_json[p] for p in prefabs}, f, separators=(",", ":"))
    measured = bake_plants.kind_profiles(os.path.join(fol, "foliage_shots.csv"), prefabs)
    prof = [photo_doc["plants"][i] if p in missing else measured[i] for i, p in enumerate(prefabs)]
    os.remove(os.path.join(fol, "foliage_shots.csv"))  # the site does not read it; the library has it

    # every plant once, back from the map's tiles (a plant near a tile edge is in each tile it reaches)
    tile, gx0, gz0, unit = index["grid"]["tile"], index["grid"]["x0"], index["grid"]["z0"], photo_doc["baseUnit"]
    margin = photo_doc["margin"]
    seen = {}
    for name in photo_doc["tiles"]:
        tx, tz = (int(v) for v in name.split("_"))
        with gzip.open(os.path.join(map_dir, "plants", f"{name}.bin.gz")) as f:
            data = f.read()
        n = int(np.frombuffer(data, "<u4", 1)[0])
        o = 4
        xs = np.frombuffer(data, "<u2", n, o); o += 2 * n
        zs = np.frombuffer(data, "<u2", n, o); o += 2 * n
        bs = np.frombuffer(data, "<u2", n, o); o += 2 * n
        ks = np.frombuffer(data, np.uint8, n, o); o += n
        ss = np.frombuffer(data, np.uint8, n, o)
        for a, b, c, d, e in zip(xs, zs, bs, ks, ss):
            ax, az = int(a) + (gx0 + tx * tile - margin) * 100, int(b) + (gz0 + tz * tile - margin) * 100
            seen[(round(ax), round(az), int(d))] = (int(c), int(e))
    keys = sorted(seen)
    x = np.array([k[0] for k in keys], float) / 100
    z = np.array([k[1] for k in keys], float) / 100
    kind = np.array([k[2] for k in keys], np.int64)
    base = np.array([seen[k][0] for k in keys], float) * unit
    scale = np.array([seen[k][1] for k in keys], float) / 100
    reach = np.array([max(p["hw"]) for p in prof])[kind] * scale

    folder = os.path.join(out_dir, "plants")
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    made, total = [], 0
    for tz in range(index["grid"]["rows"]):
        for tx in range(index["grid"]["cols"]):
            x0, z0 = gx0 + tx * tile, gz0 + tz * tile
            sel = np.nonzero((x + reach > x0) & (x - reach < x0 + tile) & (z + reach > z0) & (z - reach < z0 + tile))[0]
            if not len(sel):
                continue
            n = len(sel)
            data = (np.uint32(n).tobytes()
                    + np.round((x[sel] - x0 + margin) * 100).astype("<u2").tobytes()
                    + np.round((z[sel] - z0 + margin) * 100).astype("<u2").tobytes()
                    + np.round(base[sel] / unit).astype("<u2").tobytes()
                    + kind[sel].astype(np.uint8).tobytes()
                    + np.round(scale[sel] * 100).astype(np.uint8).tobytes())
            with open(os.path.join(folder, f"{tx}_{tz}.bin.gz"), "wb") as f:
                f.write(gzip.compress(data, 9, mtime=0))
            made.append(f"{tx}_{tz}")
            total += n
    doc = dict(photo_doc, note="made by reforger-map-tools rmtlib/foliage_mesh.py site_option (mesh library "
               f"{library['gameBuild']}); see there", tiles=made, plants=prof)
    with open(os.path.join(out_dir, "foliage.json"), "w", encoding="utf8") as f:
        json.dump(doc, f, separators=(",", ":"))
    rows, cols = index["light"]["rows"], index["light"]["cols"]
    k = bake_plants.foliage_layer(x, z, kind, scale, prof, rows, cols, gx0, gz0)
    os.makedirs(os.path.join(out_dir, "light"), exist_ok=True)
    bake_plants.write_gz(os.path.join(out_dir, "light", "foliage.bin.gz"),
                         np.clip(np.round(k / bake_plants.K_MAX * 255), 0, 255).astype(np.uint8))
    log(f"{map_dir}: {len(x):,} plants, {len(prefabs) - len(missing)} of {len(prefabs)} kinds from the library"
        + (f" (photographs for {', '.join(sorted(m.split('/')[-1] for m in missing))})" if missing else ""))
    return dict(plants=len(x), kinds=len(prefabs), from_photos=sorted(missing), k=k)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default=None, help="library file (default <workspace>/foliage-library/<build>.json.gz)")
    b.add_argument("--only", help="only prefab paths matching this regex (tests)")
    b.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    s = sub.add_parser("show")
    s.add_argument("prefab")
    o = sub.add_parser("option", help="a published map's foliage files from the library, to compare on the site")
    o.add_argument("map_dir", help="the map's folder of the site (data/maps/<id>)")
    o.add_argument("out_dir")
    o.add_argument("--build", help="library game build (default the newest library)")
    args = ap.parse_args(argv)
    if args.cmd == "option":
        site_option(args.map_dir, args.out_dir, args.build)
    elif args.cmd == "build":
        from .steam import GAME_APP, app
        out = args.out or library_path(app(GAME_APP)[1])
        build(out, args.only, args.jobs)
    else:
        print(json.dumps(record(args.prefab.split("}", 1)[-1]), indent=1)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
