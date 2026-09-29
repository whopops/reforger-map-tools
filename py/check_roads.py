"""Check a finished road export still has dirt roads and bridges.

The old tool missed both: dirt pieces that were not top-level or whose line lived
on Points, and bridge decks that are not RoadEntity. This fails if a dirt piece
has no real line, or a bridge has no line at all (a straight deck may use the
bounds centerline).

Run:  python py/check_roads.py --src "<export folder>"
"""

import argparse
import csv
import json
import os
import sys

from road_cover import REAL_WHICH


def load_tiles(folder):
    pieces = {}
    names = [fn for fn in os.listdir(folder) if fn.startswith("n_") and fn.endswith(".csv")]
    for fn in sorted(names):
        ok = os.path.join(folder, fn + ".ok")
        if not os.path.isfile(ok):
            raise SystemExit(f"{fn} has no .ok; export is not finished")
        with open(os.path.join(folder, fn), encoding="utf8", newline="") as f:
            for row in csv.DictReader(f):
                pieces[row["id"]] = {"role": row["role"], "points": []}
        pfn = "p_" + fn[2:]
        pok = os.path.join(folder, pfn + ".ok")
        if not os.path.isfile(pok):
            raise SystemExit(f"{pfn} has no .ok; export is not finished")
        with open(os.path.join(folder, pfn), encoding="utf8", newline="") as f:
            for row in csv.DictReader(f):
                piece = pieces.get(row["id"])
                if piece is None:
                    raise SystemExit(f"point for unknown id {row['id']} in {pfn}")
                piece["points"].append(row["which"])
    return pieces


def assess(pieces, min_dirt, min_bridge):
    errors = []
    counts = {"dirt": 0, "bridge": 0, "road": 0, "path": 0}
    dirt_lines = 0
    bridge_lines = 0
    for pid, piece in pieces.items():
        role = piece["role"]
        counts[role] = counts.get(role, 0) + 1
        real = sum(1 for which in piece["points"] if which in REAL_WHICH)
        if role == "dirt":
            if real < 2:
                errors.append(f"dirt {pid} has no spline ({real} real points)")
            else:
                dirt_lines += 1
        elif role == "bridge":
            if real + sum(1 for which in piece["points"] if which == "bounds") < 2:
                errors.append(f"bridge {pid} has no line")
            else:
                bridge_lines += 1
    if counts.get("dirt", 0) < min_dirt:
        errors.append(f"dirt pieces {counts.get('dirt', 0)} < {min_dirt}")
    if counts.get("bridge", 0) < min_bridge:
        errors.append(f"bridge pieces {counts.get('bridge', 0)} < {min_bridge}")
    return counts, dirt_lines, bridge_lines, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fail if dirt roads or bridges were dropped.")
    ap.add_argument("--src", required=True, help="export folder containing roads/ and roads.status.json")
    ap.add_argument("--min-dirt", type=int, default=1)
    ap.add_argument("--min-bridge", type=int, default=1)
    args = ap.parse_args(argv)
    status_path = os.path.join(args.src, "roads.status.json")
    with open(status_path, encoding="utf8") as f:
        status = json.load(f)
    if status.get("result") != "done":
        raise SystemExit(f"roads.status.json result is {status.get('result')}, not done")
    pieces = load_tiles(os.path.join(args.src, "roads"))
    counts, dirt_lines, bridge_lines, errors = assess(pieces, args.min_dirt, args.min_bridge)
    print(f"pieces {len(pieces)} dirt {counts.get('dirt', 0)} ({dirt_lines} lines) bridges {counts.get('bridge', 0)} ({bridge_lines} lines)")
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
