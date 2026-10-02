"""Reforger Map Tools: export any Arma Reforger map with Arma Reforger Tools, unattended.

  python rmt.py worlds [--refresh]                 list the worlds Workbench can see
  python rmt.py export <world> [options]           run the export jobs for one world
  python rmt.py bake <world> [--parts a,b,c]       bake the newest export into site data (out/<slug>/<build>/site)
  python rmt.py check <world>                      score the baked line of sight against the engine's sight lines
                                                   (needs the sightlines job and the los bake)
  python rmt.py fieldmap <world> [--to <folder>]   install the newest bake into the website (arma-map's everon-map:
                                                   the field map and its 3D view, trees included)

<world> is a .ent file on disk (a mod map), a resource path ("worlds/Eden/Eden.ent"), or a world's file name
("Eden"). Steam must be running and Workbench closed. See README.md and docs/.
"""

import argparse
import sys

from rmtlib.export import ALL_JOBS, JOBS, Exporter
from rmtlib.steam import Install


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workbench", help="path to ArmaReforgerWorkbenchSteamDiag.exe (found through Steam otherwise)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worlds", help="list the worlds Workbench can see")
    w.add_argument("--refresh", action="store_true", help="ask Workbench again instead of using out/worlds.txt")

    e = sub.add_parser("export", help="export one world")
    e.add_argument("world")
    e.add_argument("--jobs", default=",".join(JOBS), help=f"comma list, default {','.join(JOBS)}")
    e.add_argument("--tile", type=float, default=500, help="chunk size in metres (default 500)")
    e.add_argument("--region", help="only chunks tx0,tz0,tx1,tz1 (for tests)")
    e.add_argument("--max-chunks", type=int, default=0, help="stop each chunk job after N new chunks (for tests)")
    e.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                   help="extra job setting, passed to the plugin as -rmtNAME=VALUE (e.g. --set SatSpan=256)")
    e.add_argument("--retries", type=int, default=3)
    e.add_argument("--stall", type=int, default=600, help="seconds without progress before Workbench is killed")

    b = sub.add_parser("bake", help="turn an export into site data (out/<world>/<build>/site)")
    b.add_argument("world")
    b.add_argument("--parts", default="roads,los,places,satellite,foliage,plants",
                   help="comma list: roads, los, places, satellite, foliage, plants (default all; plants needs los "
                        "and foliage)")

    c = sub.add_parser("check", help="score the baked line of sight against the engine's own sight lines")
    c.add_argument("world", nargs="?", help="the export to score (its sightlines/check.csv and site/los)")
    c.add_argument("--csv", help="a check.csv to score instead of the export's")
    c.add_argument("--site", help="a site folder (holding los/) to score instead of the export's")

    fm = sub.add_parser("fieldmap", help="install the newest bake of a world into the website (static/data/maps/<id>/, "
                                         "the 3D view's trees and map list)")
    fm.add_argument("world")
    fm.add_argument("--to", help="the field map's folder, holding server.py (default: arma-map/everon-map beside "
                                 "this repo's folder)")
    fm.add_argument("--as", dest="map_id", help="the site's id for the world (default: everon, kolguyev or "
                                                "arland by its slug)")
    fm.add_argument("--tiles", action="store_true", help="also copy the satellite tiles for everon (its come from "
                                                         "the field map server's tile cache otherwise)")
    fm.add_argument("--photos", action="store_true", help="colour the tree kinds that have no tuned colours from the "
                                                          "foliage photos instead of plain greens")

    args = ap.parse_args(argv)
    if args.cmd == "bake":
        return bake(args)
    if args.cmd == "check":
        return check(args, ap)
    if args.cmd == "fieldmap":
        return fieldmap(args, ap)
    install = Install(args.workbench)
    ex = Exporter(install)
    if args.cmd == "worlds":
        for world in ex.list_worlds(refresh=args.refresh):
            print(world)
        return 0
    if args.cmd == "export":
        jobs = [j.strip() for j in args.jobs.split(",") if j.strip()]
        unknown = [j for j in jobs if j not in ALL_JOBS]
        if unknown:
            ap.error(f"unknown jobs: {unknown}")
        print(f"Arma Reforger build {install.game_build}, Tools build {install.tools_build}")
        manifest, failed = ex.export(args.world, jobs, args.tile, args.region, args.max_chunks, args.retries, args.stall,
                                     settings=args.set)
        if failed:
            print(f"FAILED: {', '.join(failed)}  (rerun the same command to resume)")
            return 1
        print("done")
        return 0


def newest_export(world_arg):
    """The newest export of a world, found by its manifest under out/: (manifest, its site folder)."""
    import glob
    import json
    import os

    from rmtlib.export import REPO

    a = world_arg.replace("\\", "/").lower()
    found = []
    for path in glob.glob(os.path.join(REPO, "out", "*", "*", "manifest.json")):
        with open(path, encoding="utf8") as f:
            m = json.load(f)
        world = m["world"].lower()
        if a in (world, world.split("}", 1)[-1], m["slug"], os.path.splitext(os.path.basename(world))[0]):
            found.append((os.path.getmtime(path), path, m))
    if not found:
        raise SystemExit(f"no export of '{world_arg}' under out/ (run rmt.py export first)")
    _, path, m = max(found, key=lambda t: t[0])
    return m, os.path.join(os.path.dirname(path), "site")


def check(args, ap):
    """Score a site's line-of-sight tiles against the engine's sight lines (rmtlib/check_los.py)."""
    import os

    from rmtlib import check_los

    csv_path, site = args.csv, args.site
    if args.world:
        m, export_site = newest_export(args.world)
        csv_path = csv_path or os.path.join(m["raw"], "sightlines", "check.csv")
        site = site or export_site
    if not csv_path or not site:
        ap.error("check needs a world, or both --csv and --site")
    if not os.path.isfile(csv_path):
        raise SystemExit(f"no sight lines at {csv_path} (run rmt.py export <world> --jobs sightlines)")
    if not os.path.isfile(os.path.join(site, "los", "index.json")):
        raise SystemExit(f"no baked line of sight in {site} (run rmt.py bake <world> --parts los)")
    print(f"scoring {site} against {csv_path}")
    check_los.score(csv_path, site)
    return 0


def fieldmap(args, ap):
    """Install the newest bake of a world into the website, 2D and 3D (rmtlib/fieldmap.py)."""
    import os

    from rmtlib import fieldmap as fmap
    from rmtlib.export import REPO

    m, site = newest_export(args.world)
    target = args.to or fmap.default_field_map(REPO)
    if not target or not os.path.isfile(os.path.join(target, "server.py")):
        ap.error("--to must be the field map's folder (the one holding server.py)")
    map_id = args.map_id or fmap.MAP_IDS.get(m["slug"])
    if not map_id:
        ap.error(f"no site id for {m['slug']}: pass --as <id> (and add the map to MAPS in its app.js and server.py, "
                 f"and to MAPS in rmtlib/fieldmap.py for its 3D title and start)")
    for need in ("los/index.json", "foliage/foliage_profiles.json", "foliage.json", "roads.json", "places.json"):
        if not os.path.isfile(os.path.join(site, need)):
            raise SystemExit(f"{need} isn't in {site} (run rmt.py bake {args.world})")
    photos = None
    if args.photos:
        photos = os.path.join(Install(args.workbench).game_profile, "rmt", m["slug"], m["gameBuild"], "foliage")
    fmap.install(m, site, target, map_id, tiles=args.tiles, photos=photos)
    return 0


def bake(args):
    """Bake the newest export of a world (found by its manifest under out/) into its site folder."""
    import os

    from rmtlib import bake_los, bake_roads

    m, site = newest_export(args.world)
    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    print(f"baking {m['world']} (game build {m['gameBuild']}) from {m['raw']} into {site}")
    if "roads" in parts:
        bake_roads.bake(m["raw"], site)
    if "los" in parts:
        bake_los.bake(m["raw"], site)
    if "places" in parts:
        from rmtlib import bake_places
        bake_places.bake(m["raw"], site)
    if "satellite" in parts:
        from rmtlib import satellite
        shots = os.path.join(Install(args.workbench).game_profile, "rmt", m["slug"], m["gameBuild"], "satellite")
        if os.path.isdir(shots):
            satellite.build(shots, m["raw"], os.path.join(site, "tiles"))
        else:
            print(f"satellite: no shots in {shots} (run the satellite job first)")
    if "foliage" in parts:
        from rmtlib import foliage
        photos = os.path.join(Install(args.workbench).game_profile, "rmt", m["slug"], m["gameBuild"], "foliage")
        if os.path.isfile(os.path.join(photos, "shots.csv")):
            foliage.analyse(photos, [os.path.join(site, "foliage")])
        else:
            print(f"foliage: no photographs in {photos} (run the foliage job first)")
    if "plants" in parts:
        from rmtlib import bake_plants
        bake_plants.bake(m["raw"], site)
    return 0


if __name__ == "__main__":
    sys.exit(main())
