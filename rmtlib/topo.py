"""Read BI's 2D-map geometry export (<World>.topo, written by the mapdata job / MapDataExporter).

Decoded by hand (not documented by BI). All little endian.
  file      "TOPO" <u32 version> <u32 size> <u32 end offset> <u32 0>, then sections with the same 20-byte header:
            <4-char tag> <u32 version> <u32 payload size> <u32 end offset> <u32 0>
  ROAD v2   <u32 x 8: roads per kind 0..7> <u32 levels = 6>, then per level of detail (finest first):
            <u32 count> count x (<u8 kind> <u32 n> n x (f32 x, f32 y) <u32 m> m x <u32>)
            Each road is a strip of quads: 4 points per step (left, right of one station, then right, left of the
            next); the centre line is the midpoint of each pair, the width their distance. The trailing list is
            short and rare (5 roads on Arland), meaning unknown, kept as `extra`.
            Kinds seen: 0 runway / airfield, 1 main road (dashed asphalt, ~12 m), 2 paved road (~8 m),
            3 dirt road (~4 m), 5 footpath / trail (~1.8 m). Checked against the game's road materials on
            Arland and Everon.
  BULD      <u32 5> <u32 n> n x (<u32 k> k x (f32 x, f32 y)) footprint polygons,
            <u32 m> m x (<u32 0> f32 x, f32 y, f32 dirx, f32 diry) small structures as points, then 32 zero bytes
  HILL      <u32 n> n x (<u32> <f32 height> <f32 x> <f32 y> <u32> <u32>)
  AREA, WATR, PWLN: not decoded yet.
Coordinates: x is world x; y is measured from the top of the map, so world z = size - y (size = the terrain's
extent along z). Checked on Arland: after the flip the road centre lines lie within 3 m of the game's own
road control points (median).
"""

import struct

ROAD_KINDS = {0: "runway", 1: "main", 2: "paved", 3: "dirt", 5: "footpath"}


def sections(data):
    if data[:4] != b"TOPO":
        raise ValueError("not a .topo file")
    out = {}
    pos = 20
    while pos + 20 <= len(data):
        tag = data[pos:pos + 4].decode("ascii", errors="replace")
        _ver, size, _end, _ = struct.unpack_from("<4I", data, pos + 4)
        out[tag] = (pos + 20, pos + 20 + size, _ver)
        pos = pos + 20 + size
    return out


def read(path, size_z):
    with open(path, "rb") as f:
        data = f.read()
    sec = sections(data)
    doc = {"roads": [], "buildings": [], "structures": [], "hills": []}
    flip = lambda y: size_z - y

    if "ROAD" in sec:
        s, e, _ = sec["ROAD"]
        p = s + 36                          # 8 per-kind counts + the level count
        count = struct.unpack_from("<I", data, p)[0]
        p += 4
        for _ in range(count):              # finest level only
            kind = data[p]
            n = struct.unpack_from("<I", data, p + 1)[0]
            p += 5
            pts = struct.unpack_from(f"<{2 * n}f", data, p)
            p += 8 * n
            m = struct.unpack_from("<I", data, p)[0]
            extra = list(struct.unpack_from(f"<{m}I", data, p + 4))
            p += 4 + 4 * m
            xy = list(zip(pts[0::2], pts[1::2]))
            line, widths = [], []
            for i in range(0, len(xy) - 1, 2):
                (ax, ay), (bx, by) = xy[i], xy[i + 1]
                c = ((ax + bx) / 2, flip((ay + by) / 2))
                if not line or abs(line[-1][0] - c[0]) > 1e-3 or abs(line[-1][1] - c[1]) > 1e-3:
                    line.append(c)
                    widths.append(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)
            doc["roads"].append({"kind": kind, "type": ROAD_KINDS.get(kind, f"kind{kind}"),
                                 "width": sorted(widths)[len(widths) // 2] if widths else 0,
                                 "line": line, "extra": extra})

    if "BULD" in sec:
        s, e, _ = sec["BULD"]
        p = s + 4
        n = struct.unpack_from("<I", data, p)[0]
        p += 4
        for _ in range(n):
            k = struct.unpack_from("<I", data, p)[0]
            pts = struct.unpack_from(f"<{2 * k}f", data, p + 4)
            p += 4 + 8 * k
            doc["buildings"].append([(x, flip(y)) for x, y in zip(pts[0::2], pts[1::2])])
        m = struct.unpack_from("<I", data, p)[0]
        p += 4
        for _ in range(m):
            _k, x, y, dx, dy = struct.unpack_from("<I4f", data, p)
            p += 20
            doc["structures"].append({"pos": (x, flip(y)), "dir": (dx, -dy)})

    if "HILL" in sec:
        s, e, _ = sec["HILL"]
        n = struct.unpack_from("<I", data, s)[0]
        for i in range(n):
            _a, h, x, y, _b, _c = struct.unpack_from("<If2f2I", data, s + 4 + 24 * i)
            doc["hills"].append({"pos": (x, flip(y)), "height": h})
    return doc
