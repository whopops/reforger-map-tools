"""The road network for the site: roads.json.

Source: BI's own 2D-map roads (the mapdata job's <World>.topo, see topo.py) - the roads exactly as the game's map
draws them, already merged into whole roads and typed by BI: paved, dirt, footpath, runway. If a world has no .topo
(or it has no roads), the roads job's pieces are used instead, typed by surface material with the decals dropped.

Joining: a road end is joined to another road only where the two surfaces really touch: BI draws a side road
stopping at the edge of the road it meets, so an end is joined when it lies within half of both widths plus
TOUCH_M (1 m) of the other road's centre line (at least SNAP_M, 2 m), either to that road's end or, splitting
it, to the nearest point along it. An end still loose after that is carried straight on along its own last few
metres for at most EXTEND_M (12 m); if that line hits another road it is joined where it hits (a road meeting
another at an angle stops short of its edge). Nothing else is joined. (The old importer joined loose ends up to
60 m apart in any direction and across 120 m gaps, which is where false connections came from.) Roads that cross
without either ending there are left unjoined: in 2D a bridge and a crossroads look the same. BI's roads run on
across bridges, so no bridge gaps need closing.

Output (site/roads.json):
  {"version", "source": "bi-topo" | "road-pieces", "kinds": [...],
   "nodes": [[x, z], ...], "edges": [[a, b, kind, [[x, z], ...], width], ...], "runways": [[[x, z], ...], ...]}
  kind 0 main road, 1 street, 2 dirt road, 3 foot path   (the field map's existing kinds)
BI's kinds map straight onto them: main -> main road, paved -> street, dirt -> dirt road, footpath -> foot path.
"""

import collections
import csv
import json
import math
import os
import time

import numpy as np

from . import topo

SNAP_M = 2.0
TOUCH_M = 1.0
EXTEND_M = 12.0
SIMPLIFY_M = 0.3
KINDS = ["main road", "street", "dirt road", "foot path"]


# ------------------------------------------------------------------------------------------------ sources
def material_kind(material):
    """The field map's kind for a road-piece surface material, or None for a decal (same rules as the old importer)."""
    m = material.lower()
    if "/roads/data/" not in m or "decal_" in m:
        return None
    if "trail" in m:
        return 3
    if "asphalt" in m and "dashed" in m:
        return 0
    if "asphalt" in m or "cobble" in m or "concrete" in m:
        return 1
    if "dirt" in m or "forest" in m or "gravel" in m:
        return 2
    return None


def load_pieces(raw):
    """The roads job's pieces: [(kind, material, width, [(x, z), ...])] from the spline control points."""
    path = os.path.join(raw, "roads", "roadentities.csv")
    if not os.path.isfile(path):
        return []
    pts, info = collections.defaultdict(list), {}
    with open(path, encoding="utf8", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            if r["which"] != "ctrl":
                continue
            pts[r["road"]].append((int(r["point"]), float(r["x"]), float(r["z"])))
            info[r["road"]] = (r["material"], float(r["width"] or 0), r["type"])
    out = []
    for rid, p in pts.items():
        material, width, rtype = info[rid]
        kind = material_kind(material)
        if kind is None and material == "" and rtype == "2":
            kind = 1  # a few street pieces carry no material of their own
        if kind is None or len(p) < 2:
            continue
        out.append((kind, material, width, catmull_rom([(x, z) for _, x, z in sorted(p)])))
    return out


def catmull_rom(p, step=2.0):
    """A smooth curve through the control points (centripetal Catmull-Rom), about every `step` metres."""
    p = np.asarray(p, float)
    keep = np.r_[True, np.hypot(*np.diff(p, axis=0).T) > 0.05]
    p = p[keep]
    if len(p) < 3:
        return [tuple(q) for q in p]
    ext = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = [p[0]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t1 = max(np.hypot(*(p1 - p0)), 1e-6) ** 0.5
        t2 = t1 + max(np.hypot(*(p2 - p1)), 1e-6) ** 0.5
        t3 = t2 + max(np.hypot(*(p3 - p2)), 1e-6) ** 0.5
        n = max(1, int(math.ceil(np.hypot(*(p2 - p1)) / step)))
        for t in np.linspace(t1, t2, n + 1)[1:]:
            a1 = (t1 - t) / t1 * p0 + t / t1 * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / t2 * a1 + t / t2 * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    return [tuple(q) for q in out]


# ------------------------------------------------------------------------------------------------ network
def nearest_on(line, q):
    """(distance, segment index, point) of the nearest point to q on a polyline."""
    a, b = line[:-1], line[1:]
    ab = b - a
    t = np.clip(((q - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
    pr = a + ab * t[:, None]
    d = np.hypot(*(pr - q).T)
    i = int(d.argmin())
    return float(d[i]), i, pr[i]


def rdp(pts, eps):
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, d = pts[i], pts[j] - pts[i]
        L = np.hypot(*d)
        seg = pts[i + 1:j] - a
        dist = np.abs(seg[:, 0] * d[1] - seg[:, 1] * d[0]) / L if L else np.hypot(seg[:, 0], seg[:, 1])
        k = int(np.argmax(dist))
        if dist[k] > eps:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return pts[keep]


def extend_hit(lines, ri, at_start, extend=EXTEND_M, back=5.0):
    """Where a road's end, carried straight on for up to `extend` metres, first crosses another road:
    (distance, road, segment, point, extend) or None."""
    line = lines[ri][::-1] if at_start else lines[ri]
    end = line[-1]
    i = len(line) - 2
    while i > 0 and np.hypot(*(line[i] - end)) < back:
        i -= 1
    heading = end - line[i]
    L = np.hypot(*heading)
    if L < 1e-6:
        return None
    r = heading / L * extend
    best = None
    for rj, other in enumerate(lines):
        if rj == ri:
            continue
        a = other[:-1]
        s = other[1:] - a
        denom = r[0] * s[:, 1] - r[1] * s[:, 0]
        ok = np.abs(denom) > 1e-9
        safe = np.where(ok, denom, 1.0)
        qp = a - end
        t = np.where(ok, (qp[:, 0] * s[:, 1] - qp[:, 1] * s[:, 0]) / safe, -1.0)
        u = np.where(ok, (qp[:, 0] * r[1] - qp[:, 1] * r[0]) / safe, -1.0)
        hit = ok & (t > 0) & (t <= 1) & (u >= 0) & (u <= 1)
        if hit.any():
            k = int(np.argmin(np.where(hit, t, 9.0)))
            if best is None or t[k] * extend < best[0]:
                best = (float(t[k] * extend), rj, k, end + r * t[k], extend)
    return best


def build(roads, snap=SNAP_M, touch=TOUCH_M):
    """roads: [(kind, width, [(x, z), ...])]. Joins ends that touch; returns nodes, edges and stats."""
    lines = [np.asarray(r[2], float) for r in roads]
    cuts = [dict() for _ in roads]          # road -> {position along it (segment index + t): node}
    nodes = []

    def node_at(q):
        for i, n in enumerate(nodes):
            if abs(n[0] - q[0]) <= 0.01 and abs(n[1] - q[1]) <= 0.01:
                return i
        nodes.append((float(q[0]), float(q[1])))
        return len(nodes) - 1

    def cut(ri, seg, point):
        line = lines[ri]
        a, b = line[seg], line[seg + 1]
        L = np.hypot(*(b - a))
        t = 0.0 if L == 0 else float(np.hypot(*(point - a)) / L)
        key = seg + min(max(t, 0.0), 1.0)
        for k, n in cuts[ri].items():
            if abs(k - key) < 1e-6 or np.hypot(*(np.asarray(nodes[n]) - point)) <= snap:
                return n
        n = node_at(point)
        cuts[ri][key] = n
        return n

    stats = collections.Counter()
    # every road's own ends are nodes
    for ri, line in enumerate(lines):
        cut(ri, 0, line[0])
        cut(ri, len(line) - 2, line[-1])
    # join each end to whatever it touches
    for ri, line in enumerate(lines):
        for end, seg_end in ((line[0], 0), (line[-1], len(line) - 2)):
            best = None
            for rj, other in enumerate(lines):
                if rj == ri:
                    continue
                d, seg, point = nearest_on(other, end)
                reach = max(snap, (roads[ri][1] + roads[rj][1]) / 2 + touch)
                if d <= reach and (best is None or d - reach < best[0] - best[4]):
                    best = (d, rj, seg, point, reach)
            if not best:
                best = extend_hit(lines, ri, seg_end == 0)
                if best:
                    stats["carried on"] += 1
            if not best:
                stats["dead end"] += 1
                continue
            d, rj, seg, point, _ = best
            n_other = cut(rj, seg, point)
            n_own = cut(ri, seg_end, end)
            if n_own != n_other:
                # the end moves onto the junction
                for k, v in list(cuts[ri].items()):
                    if v == n_own:
                        cuts[ri][k] = n_other
            stats["joined"] += 1
    # cut every road at its nodes
    edges = []
    for ri, (kind, width, _) in enumerate(roads):
        line = lines[ri]
        marks = sorted(cuts[ri].items())
        for (k0, n0), (k1, n1) in zip(marks, marks[1:]):
            if n0 == n1:
                continue
            s0, s1 = int(math.floor(k0)), int(math.floor(k1))
            pts = [nodes[n0]]
            pts += [tuple(line[i]) for i in range(s0 + 1, min(s1, len(line) - 2) + 1)]
            pts.append(nodes[n1])
            if len(pts) >= 2:
                edges.append([n0, n1, kind, pts, width])
    return nodes, edges, stats


# ------------------------------------------------------------------------------------------------ bake
def bake(raw, site, log=print):
    t0 = time.time()
    with open(os.path.join(raw, "probe.json"), encoding="utf8") as f:
        probe = json.load(f)
    size_z = float(probe["max"][2]) - float(probe["min"][2])
    pieces = load_pieces(raw)
    topo_files = [os.path.join(raw, "mapdata", fn) for fn in os.listdir(os.path.join(raw, "mapdata"))
                  if fn.endswith(".topo")] if os.path.isdir(os.path.join(raw, "mapdata")) else []
    roads, runways, source = [], [], "road-pieces"
    if topo_files:
        doc = topo.read(topo_files[0], size_z)
        if doc["roads"]:
            source = "bi-topo"
            for r in doc["roads"]:
                line = r["line"]
                if len(line) < 2:
                    continue
                if r["type"] == "runway":
                    runways.append(line)
                    continue
                if r["type"] == "main":
                    kind = 0
                elif r["type"] == "paved":
                    kind = 1
                elif r["type"] == "dirt":
                    kind = 2
                elif r["type"] == "footpath":
                    kind = 3
                else:
                    log(f"roads: unknown BI road kind {r['kind']}, taken as a street")
                    kind = 1
                roads.append((kind, round(r["width"], 2), line))
    if not roads:
        roads = [(k, w, line) for k, m, w, line in pieces]
    log(f"roads: {len(roads)} roads from {source}, {len(runways)} runway strips")
    nodes, edges, stats = build(roads)
    out_edges = []
    for a, b, kind, pts, width in edges:
        simple = rdp(pts, SIMPLIFY_M)
        out_edges.append([a, b, kind, [[round(x, 2), round(z, 2)] for x, z in simple], width])
    lengths = collections.Counter()
    for a, b, kind, pts, width in out_edges:
        lengths[KINDS[kind]] += float(np.hypot(*np.diff(np.asarray(pts), axis=0).T).sum())
    doc = {
        "version": int(time.time()), "source": source, "kinds": KINDS,
        "nodes": [[round(x, 2), round(z, 2)] for x, z in nodes], "edges": out_edges,
        "runways": [[[round(x, 2), round(z, 2)] for x, z in rdp(r, SIMPLIFY_M)] for r in runways],
    }
    os.makedirs(site, exist_ok=True)
    path = os.path.join(site, "roads.json")
    with open(path, "w", encoding="utf8") as f:
        json.dump(doc, f, separators=(",", ":"))
    log(f"roads: {len(nodes)} nodes, {len(out_edges)} edges; joined ends {stats['joined']}, dead ends {stats['dead end']}; "
        + ", ".join(f"{k} {v / 1000:.1f} km" for k, v in lengths.items())
        + f"; {os.path.getsize(path) / 1e6:.2f} MB ({time.time() - t0:.0f} s)")
    return doc
