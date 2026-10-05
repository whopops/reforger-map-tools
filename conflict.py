"""Conflict layers for the field map: bases, radio towers, HQ starts, supply stashes, vehicle spawns, refuel and
repair points and FIA cache spots, from a map's Conflict scenario in the game.

  python conflict.py Arland Cain          export, bake and install those maps (Cain is Kolguyev)
  python conflict.py Eden --no-install    export and bake only: out/<scenario slug>/<build>/site/conflict.json

For each world it runs the `conflict` job in Workbench on the world's scenario (worlds/MP/CTI_Campaign_<world>.ent),
bakes the result (rmtlib/bake_conflict.py) and writes it where the site picks it up: static/data/<map id>.json in the
field map (the map id from the slug in its map.json). Caves are hand-made and kept from a file already there.
Steam must be running and Workbench closed, as for rmt.py. Options: --to <field map folder>, --skip-export (bake
the newest export again), --no-install.
"""

import argparse
import json
import os
import sys

from rmtlib import bake_conflict, fieldmap, paths
from rmtlib.export import Exporter, slug_of
from rmtlib.steam import Install


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("worlds", nargs="+", help="world file names: Eden, Arland, Cain ...")
    ap.add_argument("--to", help="the field map's folder, holding server.py (default: arma-map/everon-map beside "
                                 "this repo's folder)")
    ap.add_argument("--skip-export", action="store_true", help="bake the newest export again instead of exporting")
    ap.add_argument("--no-install", action="store_true", help="don't write into the field map")
    ap.add_argument("--workbench", help="path to ArmaReforgerWorkbenchSteamDiag.exe (found through Steam otherwise)")
    args = ap.parse_args(argv)

    target = args.to or fieldmap.default_field_map(paths.REPO)
    if not args.no_install and (not target or not os.path.isfile(os.path.join(target, "server.py"))):
        ap.error("--to must be the field map's folder (the one holding server.py)")
    install = Install(args.workbench)
    ex = Exporter(install)
    failed = []
    for world in args.worlds:
        resource, _, _ = ex.resolve(world)
        stem = os.path.splitext(os.path.basename(resource))[0]
        scenario, _, _ = ex.resolve(f"CTI_Campaign_{stem}")
        print(f"== {stem}: {scenario}")
        raw = os.path.join(install.profile, "rmt", slug_of(scenario), install.game_build)
        if not args.skip_export:
            _, bad = ex.export(scenario, ["conflict"])
            if bad:
                print(f"FAILED: the conflict job on {scenario} (rerun to try again)")
                failed.append(world)
                continue
        map_id = fieldmap.site_map_id(target, slug_of(resource)) if target else None
        site_dir = os.path.join(target, "static", "data", "maps", map_id) if map_id else None
        places = _load(site_dir and os.path.join(site_dir, "places.json"))
        roads = _load(site_dir and os.path.join(site_dir, "roads.json"))
        doc = bake_conflict.bake(raw, stem, places, roads)

        out = os.path.join(paths.workspace(), slug_of(scenario), install.game_build, "site", "conflict.json")
        _write(out, doc)
        print(f"  baked: {out}")
        if args.no_install:
            continue
        if not map_id:
            print(f"  not installed: the field map has no map for {slug_of(resource)} (install it with rmt.py fieldmap)")
            failed.append(world)
            continue
        dest = os.path.join(target, "static", "data", f"{map_id}.json")
        old = _load(dest) or {}
        doc["caves"] = old.get("caves", [])  # hand-made, never exported
        _write(dest, doc)
        print(f"  installed: {dest}")
    if failed:
        print(f"not done: {', '.join(failed)}")
        return 1
    return 0


def _load(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf8") as f:
            return json.load(f)
    return None


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
