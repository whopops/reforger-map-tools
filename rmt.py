"""Reforger Map Tools: export any Arma Reforger map with Arma Reforger Tools, unattended.

  python rmt.py worlds [--refresh]                 list the worlds Workbench can see
  python rmt.py export <world> [options]           run the export jobs for one world
  python rmt.py bake <world> [--parts a,b,c]       bake the newest export into site data (out/<slug>/<build>/site)
  python rmt.py check <world>                      score the baked line of sight against the engine's sight lines
                                                   (needs the sightlines job and the los bake)
  python rmt.py fieldmap <world> [--to <folder>]   install the newest bake into the website (arma-map's everon-map:
                                                   the field map and its 3D view, trees included)
  python rmt.py run <world> --products a,b,c       export, bake (and check, install) what the products need, in one go
                                                   (roads, los, places, satellite, foliage, check; see rmtlib/products.py)
  python rmt.py detect                             what this PC has: Steam, the game, the Tools, Workbench, mods

Global options (before the command): --workspace <folder> puts manifests and site data there instead of out/;
--events prints JSON lines for the GUI (rmtlib/events.py) instead of text.

<world> is a .ent file on disk (a mod map), a resource path ("worlds/Eden/Eden.ent"), or a world's file name
("Eden"). Steam must be running and Workbench closed. See README.md and docs/.
"""

import argparse
import sys

from rmtlib import events, paths
from rmtlib.export import ALL_JOBS, JOBS, Exporter
from rmtlib.steam import Install


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workbench", help="path to ArmaReforgerWorkbenchSteamDiag.exe (found through Steam otherwise)")
    ap.add_argument("--workspace", help="folder for manifests and site data (default: out/ in this repo)")
    ap.add_argument("--events", action="store_true", help="print JSON lines for the GUI instead of text")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worlds", help="list the worlds Workbench can see")
    w.add_argument("--refresh", action="store_true", help="ask Workbench again instead of using out/worlds.txt")

    e = sub.add_parser("export", help="export one world")
    e.add_argument("world")
    e.add_argument("--jobs", default=",".join(JOBS), help=f"comma list, default {','.join(JOBS)}")
    _export_options(e)

    b = sub.add_parser("bake", help="turn an export into site data (out/<world>/<build>/site)")
    b.add_argument("world")
    b.add_argument("--parts", default="roads,los,places,satellite,relief,foliage,plants",
                   help="comma list: roads, los, places, satellite, relief, foliage, plants (default all; plants "
                        "needs los and foliage)")

    c = sub.add_parser("check", help="score the baked line of sight against the engine's own sight lines")
    c.add_argument("world", nargs="?", help="the export to score (its sightlines/check.csv and site/los)")
    c.add_argument("--csv", help="a check.csv to score instead of the export's")
    c.add_argument("--site", help="a site folder (holding los/) to score instead of the export's")

    fm = sub.add_parser("fieldmap", help="install the newest bake of a world into the website (static/data/maps/<id>/, "
                                         "its map.json and the 3D view's trees)")
    fm.add_argument("world")
    _fieldmap_options(fm)

    r = sub.add_parser("run", help="export and bake what the chosen products need (and check and install)")
    r.add_argument("world")
    r.add_argument("--products", required=True, help="comma list: roads, los, places, satellite, relief, foliage, check")
    r.add_argument("--install", action="store_true", help="install the result into the field map afterwards")
    _export_options(r)
    _fieldmap_options(r)

    sub.add_parser("detect", help="what this PC has (Steam, the game, the Tools, Workbench, mods)")

    args = ap.parse_args(argv)
    if args.workspace:
        paths.set_workspace(args.workspace)
    if args.events:
        events.enable()
        return _guarded(args, ap)
    return dispatch(args, ap)


def _export_options(p):
    p.add_argument("--tile", type=float, default=500, help="chunk size in metres (default 500)")
    p.add_argument("--region", help="only chunks tx0,tz0,tx1,tz1 (for tests)")
    p.add_argument("--max-chunks", type=int, default=0, help="stop each chunk job after N new chunks (for tests)")
    p.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                   help="extra job setting, passed to the plugin as -rmtNAME=VALUE (e.g. --set SatSpan=256)")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--stall", type=int, default=600, help="seconds without progress before Workbench is killed")


def _fieldmap_options(p):
    p.add_argument("--to", help="the field map's folder, holding server.py (default: arma-map/everon-map beside "
                                "this repo's folder)")
    p.add_argument("--as", dest="map_id", help="the site's id for the world (default: the site's map whose "
                                               "map.json has the world's slug; needed for a new map)")
    p.add_argument("--title", help="the map's name on the site (default: the one in its map.json, or the world's "
                                   "name for a new map)")
    p.add_argument("--tiles", action="store_true", help="also copy the satellite tiles for a map whose map.json names "
                                                        "an upstream tile server (Everon for now)")
    p.add_argument("--photos", action="store_true", help="colour the tree kinds that have no tuned colours from the "
                                                         "foliage photos instead of plain greens")


def _guarded(args, ap):
    """With --events: every way out ends in one "done" event, and errors become "error" events."""
    import traceback

    from rmtlib.workbench import JobFailed
    try:
        code = dispatch(args, ap) or 0
    except SystemExit as e:
        if isinstance(e.code, int) or e.code is None:
            code = e.code or 0
        else:
            events.emit("error", message=str(e.code))
            code = 1
    except JobFailed as e:
        events.emit("error", message=str(e))
        code = 1
    except Exception as e:
        print(traceback.format_exc(), file=sys.stderr)
        events.emit("error", message=f"{type(e).__name__}: {e}")
        code = 1
    events.emit("done", ok=code == 0, code=code)
    return code


def dispatch(args, ap):
    if args.cmd == "bake":
        return bake(args)
    if args.cmd == "check":
        return check(args, ap)
    if args.cmd == "fieldmap":
        return fieldmap(args, ap)
    if args.cmd == "detect":
        return detect(args)
    install = Install(args.workbench)
    ex = Exporter(install)
    if args.cmd == "worlds":
        worlds = ex.list_worlds(refresh=args.refresh)
        events.emit("result", worlds=worlds)
        if not events.enabled():
            for world in worlds:
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
    if args.cmd == "run":
        return run(args, ap, install, ex)


def detect(args):
    from rmtlib import detect as det
    checks = det.report(args.workbench)
    events.emit("result", checks=checks)
    if not events.enabled():
        marks = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
        for c in checks:
            print(f"{marks[c['state']]}  {c['label']}: {c['value']}" + (f"\n        {c['hint']}" if c["hint"] else ""))
    return 0 if det.ready(checks) else 1


def run_dir(m):
    import os
    return os.path.join(paths.workspace(), m["slug"], m["gameBuild"])


def newest_export(world_arg):
    """The newest export of a world, found by its manifest in the workspace: (manifest, its site folder)."""
    import glob
    import json
    import os

    a = world_arg.replace("\\", "/").lower()
    found = []
    for path in glob.glob(os.path.join(paths.workspace(), "*", "*", "manifest.json")):
        with open(path, encoding="utf8") as f:
            m = json.load(f)
        world = m["world"].lower()
        if a in (world, world.split("}", 1)[-1], m["slug"], os.path.splitext(os.path.basename(world))[0]):
            found.append((os.path.getmtime(path), path, m))
    if not found:
        raise SystemExit(f"no export of '{world_arg}' in {paths.workspace()} (run rmt.py export first)")
    _, path, m = max(found, key=lambda t: t[0])
    return m, os.path.join(os.path.dirname(path), "site")


def check(args, ap):
    """Score a site's line-of-sight tiles against the engine's sight lines (rmtlib/check_los.py)."""
    import os

    csv_path, site = args.csv, args.site
    if args.world:
        m, export_site = newest_export(args.world)
        csv_path = csv_path or os.path.join(m["raw"], "sightlines", "check.csv")
        site = site or export_site
    if not csv_path or not site:
        ap.error("check needs a world, or both --csv and --site")
    score_los(csv_path, site)
    return 0


def score_los(csv_path, site):
    import os

    from rmtlib import check_los

    if not os.path.isfile(csv_path):
        raise SystemExit(f"no sight lines at {csv_path} (run rmt.py export <world> --jobs sightlines)")
    if not os.path.isfile(os.path.join(site, "los", "index.json")):
        raise SystemExit(f"no baked line of sight in {site} (run rmt.py bake <world> --parts los)")
    print(f"scoring {site} against {csv_path}")
    result = check_los.score(csv_path, site)
    events.emit("result", check=result)
    return result


def fieldmap(args, ap):
    """Install the newest bake of a world into the website, 2D and 3D (rmtlib/fieldmap.py)."""
    m, site = newest_export(args.world)
    install_site(args, ap, m, site)
    return 0


def install_site(args, ap, m, site):
    import os

    from rmtlib import fieldmap as fmap

    target = args.to or fmap.default_field_map(paths.REPO)
    if not target or not os.path.isfile(os.path.join(target, "server.py")):
        ap.error("--to must be the field map's folder (the one holding server.py)")
    map_id = args.map_id or fmap.site_map_id(target, m["slug"])
    if not map_id:
        ap.error(f"the site has no map for {m['slug']} yet: pass --as <id> (lower case, e.g. --as {m['world'].lower()}) "
                 f"to add it, and --title for its name")
    for need in ("los/index.json", "foliage/foliage_profiles.json", "foliage.json", "roads.json", "places.json"):
        if not os.path.isfile(os.path.join(site, need)):
            raise SystemExit(f"{need} isn't in {site} (run rmt.py bake {m['slug']})")
    photos = None
    if args.photos:
        photos = os.path.join(Install(args.workbench).game_profile, "rmt", m["slug"], m["gameBuild"], "foliage")
    fmap.install(m, site, target, map_id, tiles=args.tiles, photos=photos, title=args.title)


def bake(args):
    """Bake the newest export of a world (found by its manifest in the workspace) into its site folder."""
    m, site = newest_export(args.world)
    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    bake_parts(m, site, parts, args.workbench)
    return 0


def bake_parts(m, site, parts, workbench=None):
    """Run the bake parts in order. Returns the parts that had nothing to bake from (shots or photos missing)."""
    import os

    from rmtlib import bake_los, bake_roads

    print(f"baking {m['world']} (game build {m['gameBuild']}) from {m['raw']} into {site}")
    missing = []
    for part in ("roads", "los", "places", "satellite", "relief", "foliage", "plants"):
        if part not in parts:
            continue
        events.step(f"bake:{part}", "start")
        ok = True
        if part == "roads":
            bake_roads.bake(m["raw"], site)
        elif part == "los":
            bake_los.bake(m["raw"], site)
        elif part == "places":
            from rmtlib import bake_places
            bake_places.bake(m["raw"], site)
        elif part == "satellite":
            from rmtlib import satellite
            shots = os.path.join(Install(workbench).game_profile, "rmt", m["slug"], m["gameBuild"], "satellite")
            if os.path.isdir(shots):
                satellite.build(shots, m["raw"], os.path.join(site, "tiles"))
            else:
                print(f"satellite: no shots in {shots} (run the satellite job first)")
                ok = False
        elif part == "relief":
            from rmtlib import relief
            tga = relief.picture(m["raw"])
            los = os.path.join(site, "los")
            if tga and os.path.isfile(os.path.join(los, "index.json")):
                relief.build(los, tga, float(m["probe"]["max"][0] - m["probe"]["min"][0]), os.path.join(site, "relief"))
            else:
                print(f"relief: needs the mapdata job's picture ({m['raw']}\\mapdata) and a baked line of sight ({los})")
                ok = False
        elif part == "foliage":
            from rmtlib import foliage
            photos = os.path.join(Install(workbench).game_profile, "rmt", m["slug"], m["gameBuild"], "foliage")
            if os.path.isfile(os.path.join(photos, "shots.csv")):
                foliage.analyse(photos, [os.path.join(site, "foliage")])
            else:
                print(f"foliage: no photographs in {photos} (run the foliage job first)")
                ok = False
        elif part == "plants":
            from rmtlib import bake_plants
            bake_plants.bake(m["raw"], site)
        events.step(f"bake:{part}", "done" if ok else "failed")
        if not ok:
            missing.append(part)
    return missing


def run(args, ap, install, ex):
    """Everything the chosen products need, in order: export jobs, bake parts, then the check and the install."""
    import os
    import time

    from rmtlib import products

    t0 = time.time()
    chosen = [p.strip() for p in args.products.split(",") if p.strip()]
    plan = products.plan(chosen, install=args.install)
    resource, _, _ = ex.resolve(args.world)
    events.emit("plan", world=resource, products=plan.products, steps=plan.steps)
    print(f"Arma Reforger build {install.game_build}, Tools build {install.tools_build}")
    print(f"products: {', '.join(plan.products)}")
    print(f"export jobs: {', '.join(plan.jobs)}; bake: {', '.join(plan.bakes) or 'nothing'}")

    manifest, failed = ex.export(args.world, plan.jobs, args.tile, args.region, args.max_chunks, args.retries,
                                 args.stall, settings=args.set)
    for job in plan.jobs:
        events.step(f"export:{job}", "failed" if job in failed else "done")
    site = os.path.join(run_dir(manifest), "site")
    if failed:
        print(f"FAILED: {', '.join(failed)}  (run again to resume: finished jobs and chunks are kept)")
        for s in plan.steps:
            if not s["id"].startswith("export:"):
                events.step(s["id"], "skipped")
        events.emit("error", message=f"export failed: {', '.join(failed)}",
                    hint="Run again to resume. See docs/troubleshooting.md for the message in the log.")
        return 1

    missing = bake_parts(manifest, site, plan.bakes, args.workbench)
    if missing:
        events.emit("error", message=f"nothing to bake for: {', '.join(missing)}")
        return 1
    if plan.check:
        events.step("check", "start")
        score_los(os.path.join(manifest["raw"], "sightlines", "check.csv"), site)
        events.step("check", "done")
    if plan.install:
        events.step("install", "start")
        install_site(args, ap, manifest, site)
        events.step("install", "done")
    print(f"done in {time.time() - t0:.0f} s: {site}")
    events.emit("result", site=site, manifest=os.path.join(run_dir(manifest), "manifest.json"),
                seconds=round(time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
