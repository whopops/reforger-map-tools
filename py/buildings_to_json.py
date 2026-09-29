"""Turn a finished building export into one JSON file.

Reads buildings/b_*.csv, d_*.csv and f_*.csv (each with its .ok) and export.status.json.
Writes id, prefab, position, yaw, bounds, enterable, floors, entrances.
Refuses to write anything over 40 MB. Does not invent rows: an export with no
buildings writes {"buildings": []}. samples/buildings.sample.json is that empty file.

Run:  python py/buildings_to_json.py --src "<export folder>" --out buildings.json [--map maps/everon.json]
"""

import argparse
import csv
import json
import math
import os
import sys

MAX_BYTES = 40 * 1024 * 1024


def tile_index(name):
    stem = name[:-4]
    _prefix, tx, tz = stem.split("_")
    return int(tx), int(tz)


def num(text):
    return float(text)


def load_status(folder):
    path = os.path.join(folder, "export.status.json")
    with open(path, encoding="utf8") as f:
        status = json.load(f)
    if status.get("result") != "done":
        raise SystemExit(f"export.status.json result is {status.get('result')}, not done")
    return status


def require_grid(buildings, size, tile):
    n = math.ceil(size / tile)
    missing = []
    for tz in range(n):
        for tx in range(n):
            for prefix in ("b", "d", "f"):
                fn = f"{prefix}_{tx}_{tz}.csv"
                if not os.path.isfile(os.path.join(buildings, fn)) or not os.path.isfile(os.path.join(buildings, fn + ".ok")):
                    missing.append(fn)
    if missing:
        raise SystemExit("export is missing " + ", ".join(missing[:8]))


def read_export(folder, size=None, tile=None):
    load_status(folder)
    buildings = os.path.join(folder, "buildings")
    if size is not None and tile is not None:
        require_grid(buildings, size, tile)
    names = [fn for fn in os.listdir(buildings) if fn.startswith("b_") and fn.endswith(".csv")]
    out = []
    for fn in sorted(names, key=tile_index):
        if not os.path.isfile(os.path.join(buildings, fn + ".ok")):
            raise SystemExit(f"{fn} has no .ok")
        tx, tz = tile_index(fn)
        for prefix in ("d", "f"):
            sibling = f"{prefix}_{tx}_{tz}.csv"
            if not os.path.isfile(os.path.join(buildings, sibling + ".ok")):
                raise SystemExit(f"{sibling} has no .ok")
        floors = {}
        with open(os.path.join(buildings, f"f_{tx}_{tz}.csv"), encoding="utf8", newline="") as f:
            for row in csv.DictReader(f):
                floors.setdefault(row["id"], []).append({"y": num(row["y"]), "samples": int(float(row["samples"]))})
        entrances = {}
        with open(os.path.join(buildings, f"d_{tx}_{tz}.csv"), encoding="utf8", newline="") as f:
            for row in csv.DictReader(f):
                entrances.setdefault(row["id"], []).append({
                    "kind": row["kind"],
                    "position": [num(row["x"]), num(row["y"]), num(row["z"])],
                    "class": row["class"],
                })
        with open(os.path.join(buildings, fn), encoding="utf8", newline="") as f:
            for row in csv.DictReader(f):
                ident = row["id"]
                out.append({
                    "id": ident,
                    "prefab": row["prefab"],
                    "position": [num(row["x"]), num(row["y"]), num(row["z"])],
                    "yaw": num(row["yaw"]),
                    "bounds": {
                        "min": [num(row["minx"]), num(row["miny"]), num(row["minz"])],
                        "max": [num(row["maxx"]), num(row["maxy"]), num(row["maxz"])],
                    },
                    "enterable": int(float(row["enterable"])),
                    "floors": floors.get(ident, []),
                    "entrances": entrances.get(ident, []),
                })
    return {"buildings": out}


def dumps(doc):
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False)


def write_doc(doc, path, max_bytes):
    text = dumps(doc) + "\n"
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise SystemExit(f"refusing to write {path}: {size} bytes exceeds {max_bytes}")
    tmp = path + ".partial"
    with open(tmp, "w", encoding="utf8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    return size


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write one building JSON from a finished export.")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--map", help="maps/everon.json; when set, every tile must be present")
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    args = ap.parse_args(argv)
    size = tile = None
    if args.map:
        with open(args.map, encoding="utf8") as f:
            cfg = json.load(f)
        size, tile = float(cfg["size"]), float(cfg["tile"])
    doc = read_export(args.src, size, tile)
    written = write_doc(doc, args.out, args.max_bytes)
    print(f"{len(doc['buildings'])} buildings, {written} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
