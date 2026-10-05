"""Export a world: resolve it, run each job in Workbench with retries, and keep a manifest of the run."""

import datetime
import glob
import json
import math
import os
import re
import time

from . import addons, paths
from .workbench import REPO, JobFailed, Workbench, read_status, succeeded

JOBS = ["probe", "mapdata", "roads", "names", "entities", "terrain", "surface"]
ALL_JOBS = JOBS + ["sightlines", "satellite", "foliage", "conflict", "ballistics", "mortar_tables"]
RESEARCH_JOBS = ["foliagetrace", "materials"]  # accepted by --jobs, never listed for users (RMT_FoliageTrace.c, RMT_MaterialsJob.c)
CHUNK_JOBS = {"entities": "objects", "terrain": "terrain", "surface": "surface"}
# What each Workbench job must leave behind (under the raw run folder) for its status to count as success.
OUTPUTS = {
    "probe": ["probe.json"], "mapdata": ["mapdata"], "roads": ["roads/roadentities.csv"],
    "names": ["names/descriptors.csv"], "entities": ["objects"], "terrain": ["terrain"], "surface": ["surface"],
    "sightlines": ["sightlines/check.csv"], "conflict": ["conflict/entities.csv"],
    "ballistics": ["ballistics/sim.csv"], "mortar_tables": ["mortar_tables/tables.csv"],
    "foliagetrace": ["foliagetrace/rays.csv"], "materials": ["materials/params.csv"],
}


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def slug_of(resource):
    guid = re.match(r"\{([0-9A-Fa-f]{16})\}", resource)
    stem = os.path.splitext(os.path.basename(resource))[0]
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return f"{s}-{guid.group(1)[:6].lower()}" if guid else s


def addon_of_file(path):
    """For a world file on disk: (resource path inside its addon, addon GUID, addon's parent folder)."""
    path = os.path.abspath(path)
    d = os.path.dirname(path)
    while True:
        gprojs = glob.glob(os.path.join(d, "*.gproj"))
        if gprojs:
            with open(gprojs[0], encoding="utf8", errors="replace") as f:
                m = re.search(r'GUID\s+"([0-9A-Fa-f]{16})"', f.read())
            rel = os.path.relpath(path, d).replace("\\", "/")
            return rel, (m.group(1) if m else None), os.path.dirname(d)
        parent = os.path.dirname(d)
        if parent == d:
            raise SystemExit(f"{path} is not inside an addon (no .gproj above it)")
        d = parent


class Exporter:
    def __init__(self, install, log=print):
        self.install = install
        self.log = log

    # ---------------------------------------------------------------------------------------------
    def list_worlds(self, refresh=False):
        cache = os.path.join(paths.workspace(), "worlds.txt")
        if refresh or not os.path.isfile(cache):
            wb = Workbench(self.install, log=self.log)
            code, _, _ = wb.run("worlds", "rmt/_worlds", stall=300)
            src = os.path.join(self.install.profile, "rmt", "_worlds", "worlds.txt")
            if code != 0 or not os.path.isfile(src):
                raise SystemExit("could not list worlds")
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(src, encoding="utf8", errors="replace") as f, open(cache, "w", encoding="utf8") as g:
                g.write(f.read())
        with open(cache, encoding="utf8") as f:
            return [w.strip() for w in f if w.strip()]

    def resolve(self, arg):
        """A world from what the user typed: a .ent file on disk, a resource path, or a name.
        Returns (resource, extra addon GUIDs, extra addon folders)."""
        if os.path.isfile(arg):
            rel, guid, parent = addon_of_file(arg)
            return rel, ([guid] if guid else []), [parent]
        # Every installed addon's resource database first (instant, and it knows which mod a world needs); the world
        # list Workbench writes (rmt.py worlds) is the fallback.
        found = addons.find_world(self.install, arg)
        if found:
            return found
        worlds = self.list_worlds()
        a = arg.replace("\\", "/").lower()
        exact = [w for w in worlds if w.lower() == a or w.lower().split("}", 1)[-1] == a]
        if exact:
            return exact[0], [], []
        by_stem = [w for w in worlds if os.path.splitext(os.path.basename(w))[0].lower() == a]
        if len(by_stem) == 1:
            return by_stem[0], [], []
        if len(by_stem) > 1:
            raise SystemExit(f"'{arg}' matches several worlds:\n  " + "\n  ".join(by_stem))
        raise SystemExit(f"no world '{arg}'. Run `rmt.py worlds` to list them, or pass the .ent file's path.")

    # ---------------------------------------------------------------------------------------------
    def export(self, world_arg, jobs=None, tile=500, region=None, max_chunks=0, retries=3, stall=600, fresh=False, settings=()):
        resource, guids, dirs = self.resolve(world_arg)
        slug = slug_of(resource)
        build = self.install.game_build
        out_rel = f"rmt/{slug}/{build}"
        raw = os.path.join(self.install.profile, "rmt", slug, build)
        run_dir = os.path.join(paths.workspace(), slug, build)
        os.makedirs(run_dir, exist_ok=True)
        manifest_path = os.path.join(run_dir, "manifest.json")
        manifest = {}
        if os.path.isfile(manifest_path) and not fresh:
            with open(manifest_path, encoding="utf8") as f:
                manifest = json.load(f)
        if fresh and os.path.isdir(raw):
            raise SystemExit(f"--fresh: delete {raw} yourself first (rmt never deletes exports)")
        manifest.update({
            "world": resource, "slug": slug, "gameBuild": build, "toolsBuild": self.install.tools_build,
            "raw": raw, "tile": tile, "addons": guids,
        })
        manifest.setdefault("created", now())
        manifest.setdefault("jobs", {})

        wb = Workbench(self.install, addon_dirs=dirs, extra_guids=guids, log=self.log)
        extra = [f"-rmtTile={tile}"]
        if region:
            extra.append(f"-rmtRegion={region}")
        if max_chunks:
            extra.append(f"-rmtMaxChunks={max_chunks}")
        for s in settings:
            name, _, value = s.partition("=")
            extra.append(f"-rmt{name}={value}")

        self.log(f"world {resource}  ->  {raw}")
        jobs = [j for j in (jobs or JOBS)]
        wb_jobs = [j for j in jobs if j not in ("satellite", "foliage")]
        game_run = os.path.join(self.install.game_profile, *out_rel.split("/"))
        game_outputs = {"satellite": [os.path.join(game_run, "satellite")],
                        "foliage": [os.path.join(game_run, "foliage", "shots.csv")]}

        def ok(st, job=None):
            outputs = game_outputs.get(job) or [os.path.join(raw, *p.split("/")) for p in OUTPUTS.get(job, ())]
            return succeeded(st, outputs)

        def save():
            manifest["updated"] = now()
            with open(manifest_path, "w", encoding="utf8") as f:
                json.dump(manifest, f, indent=2)

        def record(job, status, seconds):
            manifest["jobs"][job] = {"finished": now(), "seconds": seconds, "status": status}
            if job == "probe" and ok(status, job):
                with open(os.path.join(raw, "probe.json"), encoding="utf8") as f:
                    manifest["probe"] = json.load(f)
            if ok(status, job):
                self.log(f"  [{job}] {status['result']}: {status.get('items')} items"
                         + (f" ({status['remaining']} remaining: {status.get('reason')})" if status["result"] == "partial" else ""))
            elif status:
                self.log(f"  [{job}] {status.get('result')}: {status.get('reason') or 'its output is missing or empty'}")
            save()

        # All Workbench jobs on one load of the world. After a crash or a stall, relaunch with the jobs that
        # have not written a finished status yet (the chunk jobs also skip their finished chunks).
        remaining = list(wb_jobs)
        for attempt in range(1, retries + 1):
            if not remaining:
                break
            t0 = time.time()
            code = None
            try:
                code, _, _ = wb.run(remaining, out_rel, resource, extra, stall=stall)
            except JobFailed as e:
                self.log(f"  [workbench] attempt {attempt}: {e}")
                if "script error" in str(e):
                    break
            if code == 3:
                raise SystemExit(f"the world did not load: {resource}")
            seconds = round(time.time() - t0)
            still = []
            for job in remaining:
                st = read_status(wb.status_path(out_rel, job))
                if ok(st, job):
                    record(job, st, seconds)
                else:
                    if st:
                        self.log(f"  [{job}] {st.get('result')}: {st.get('reason') or 'its output is missing or empty'}")
                    still.append(job)
            if still:
                self.log(f"  [workbench] attempt {attempt}: exit {code}; not finished: {', '.join(still)}")
            remaining = still
        failed = list(remaining)
        for job in failed:
            manifest["jobs"][job] = {"finished": now(), "status": None}
            self.log(f"  [{job}] FAILED")

        # The satellite pictures, in the game itself.
        if "satellite" in jobs:
            t0 = time.time()
            status = None
            for attempt in range(1, retries + 1):
                try:
                    code, _, status = wb.run_game("satellite", out_rel, resource,
                                                  extra + self.satellite_args(manifest, settings), stall=stall)
                except JobFailed as e:
                    self.log(f"  [satellite] attempt {attempt}: {e}")
                    status = None
                    if "script error" in str(e):
                        break
                    continue
                if ok(status, "satellite"):
                    break
                self.log(f"  [satellite] attempt {attempt}: exit {code}, status {status}")
            record("satellite", status, round(time.time() - t0))
            if not ok(status, "satellite"):
                failed.append("satellite")
                self.log("  [satellite] FAILED")

        # The plant photographs, in the game, on an empty world (nothing in the way). The plant list comes from
        # this map's entities export, so every kind on this map is measured, whatever world is used to shoot it.
        if "foliage" in jobs:
            from . import foliage
            t0 = time.time()
            given = {s.partition("=")[0]: s.partition("=")[2] for s in settings}
            n = foliage.plant_list(raw, os.path.join(game_run, "foliage", "plants.csv"),
                                   int(given.get("FoliageLimit", 0)))
            empty, _, _ = self.resolve(given.get("FoliageWorld", "EmptyArland"))
            self.log(f"  [foliage] {n} kinds of tree and bush, photographed on {empty}")
            fargs = [a for a in extra if not a.startswith("-rmtFoliageWorld")]
            if "FoliageSpot" not in given:
                fargs.append("-rmtFoliageSpot=2048,2048")
            if "FoliageLod" not in given:
                fargs.append("-rmtFoliageLod=25,50,100,200,300")
            # convert the photographs to lossless PNG while the capture runs (6.2 MB BMP -> about 1 MB)
            import threading
            photos = os.path.join(game_run, "foliage")
            stop = threading.Event()

            def convert():
                while not stop.wait(20):
                    foliage.bmp_to_png(photos)

            converter = threading.Thread(target=convert, daemon=True)
            converter.start()
            status = None
            for attempt in range(1, retries + 1):
                try:
                    code, _, status = wb.run_game("foliage", out_rel, empty, fargs, stall=stall, flag="-rmtFoliage",
                                                  screen=(int(given.get("FoliageWidth", 2560)),
                                                          int(given.get("FoliageHeight", 1440)),
                                                          given.get("FoliageMode", "BORDERLESS")))
                except JobFailed as e:
                    self.log(f"  [foliage] attempt {attempt}: {e}")
                    status = None
                    if "script error" in str(e):
                        break
                    continue
                if ok(status, "foliage"):
                    break
            stop.set()
            converter.join()
            foliage.bmp_to_png(photos, min_age=0)
            record("foliage", status, round(time.time() - t0))
            if not ok(status, "foliage"):
                failed.append("foliage")
                self.log("  [foliage] FAILED")
        save()
        return manifest, failed

    @staticmethod
    def satellite_args(manifest, settings):
        """The capture grid from the probe: squares of SatSpan metres (default 400) over the terrain bounds.
        Shots are perspective with a narrow lens (SatFov degrees, default 15), from high enough that a square
        fills the picture's height even over the highest ground (lower ground is seen wider, so shots overlap).
        --set SatCenters=... (test spots) replaces the grid."""
        given = {s.partition("=")[0]: s.partition("=")[2] for s in settings}
        probe = manifest.get("probe")
        if not probe:
            raise JobFailed("satellite needs the probe job first (run --jobs probe,satellite)")
        (x0, _, z0), (x1, y1, z1) = probe["min"], probe["max"]
        span = float(given.get("SatSpan", 400))
        fov = float(given.get("SatFov", 15))
        out = []
        if "SatSpan" not in given:
            out.append(f"-rmtSatSpan={span:g}")
        if "SatFov" not in given:
            out.append(f"-rmtSatFov={fov:g}")
        if "SatHeight" not in given:
            height = max(y1, 0) + (span / 2) / math.tan(math.radians(fov / 2)) * 1.1
            out.append(f"-rmtSatHeight={height:.0f}")
        if "SatCenters" not in given and "SatGrid" not in given:
            cols = int(-(-(x1 - x0) // span))
            rows = int(-(-(z1 - z0) // span))
            out.append(f"-rmtSatGrid={x0:g},{z0:g},{cols},{rows},{span:g}")
        return out
