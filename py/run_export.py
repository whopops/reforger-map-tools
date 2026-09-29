"""Start a map export from another program and let it finish alone.

Workbench is launched with -run and -plugin=MapExportPlugin. Nobody has to
click a tool button. Each job is relaunched until its status file says done
(Workbench is closed and opened again between launches, a few tiles at a time).
Then the Python steps run: building JSON, the dirt/bridge check, and satellite
tiles.

An external program should start one of these and wait for the exit code:

  python py/run_export.py --map everon
  scripts\\run_export.cmd --map everon

It can also poll <export>/pipeline.status.json while the process is running.
Exit codes: 0 done, 1 a step failed, 2 the command itself is wrong (no map,
no Workbench), 3 the world did not load.

The editor camera fov and far plane still have to be set once in Workbench
before a satellite run. No script API can set them. Everything else is unattended.
"""

import argparse
import json
import math
import os
import subprocess
import sys

import buildings_to_json
import check_roads
import make_tiles

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
JOBS = ("buildings", "roads", "satellite")
STATUS_NAME = {
    "buildings": "export.status.json",
    "roads": "roads.status.json",
    "satellite": "satellite.status.json",
}


def resolve_map(text):
    if text.endswith(".json"):
        path = text if os.path.isabs(text) else os.path.join(os.getcwd(), text)
    else:
        path = os.path.join(REPO, "maps", text + ".json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf8") as f:
        cfg = json.load(f)
    if not cfg.get("world"):
        return None
    name = os.path.splitext(os.path.basename(path))[0]
    return path, name, cfg


def default_profile():
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, "Documents", "My Games", "ArmaReforgerWorkbench", "profile")


def export_dir(profile, map_name):
    return os.path.join(profile, "reforger_map", map_name)


def find_workbench(explicit):
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    tail = ("Steam", "steamapps", "common", "Arma Reforger Tools", "Workbench", "ArmaReforgerWorkbenchSteam.exe")
    candidates = [explicit, os.environ.get("ARMA_REFORGER_WORKBENCH"), os.path.join(pf86, *tail), os.path.join(pf, *tail)]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def workbench_command(exe, cfg, job, max_tiles, map_name, fov, height):
    cmd = [
        exe,
        "-wbModule=WorldEditor",
        "-run",
        "-load",
        str(cfg["world"]),
        "-plugin=MapExportPlugin",
        "-job=" + job,
        "-size=" + str(cfg["size"]),
        "-tile=" + str(cfg["tile"]),
        "-buildingStep=" + str(cfg["buildingStep"]),
        "-maxTiles=" + str(max_tiles),
        "-out=$profile:reforger_map/" + map_name,
    ]
    if job == "satellite" and fov:
        cmd.append("-fov=" + str(fov))
    if job == "satellite" and height:
        cmd.append("-height=" + str(height))
    return cmd


def launch_process(cmd):
    proc = subprocess.run(cmd)
    return proc.returncode if proc.returncode is not None else 1


def write_json(path, doc):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".partial"
    with open(tmp, "w", encoding="utf8", newline="\n") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def call_main(fn, argv):
    try:
        code = fn(argv)
    except SystemExit as exc:
        if exc.code is None:
            code = 0
        elif isinstance(exc.code, int):
            code = exc.code
        else:
            print(exc.code, file=sys.stderr)
            code = 1
    if code is None:
        code = 0
    return code


def run_workbench_job(job, cfg, src, command, launch):
    status_path = os.path.join(src, STATUS_NAME[job])
    tiles = int(math.ceil(float(cfg["size"]) / float(cfg["tile"])))
    limit = tiles * tiles + 2
    previous = None
    for launch_n in range(1, limit + 1):
        print(f"MapExport {job} launch {launch_n}", flush=True)
        code = launch(command)
        if code == 3:
            return {"name": job, "result": "failed", "exit": 3, "error": "world did not load", "launches": launch_n}
        if not os.path.isfile(status_path):
            return {
                "name": job,
                "result": "failed",
                "exit": 1,
                "error": f"no {STATUS_NAME[job]} after Workbench exited {code}",
                "launches": launch_n,
            }
        with open(status_path, encoding="utf8") as f:
            status = json.load(f)
        result = status.get("result")
        remaining = status.get("remaining")
        print(f"{result}: made {status.get('made')}, skipped {status.get('skipped')}, remaining {remaining}", flush=True)
        step = {"name": job, "result": result, "exit": 0 if result == "done" else 1, "launches": launch_n}
        step.update({k: status.get(k) for k in ("made", "skipped", "remaining")})
        if result == "done":
            return step
        if result == "failed":
            step["error"] = "Workbench reported failed"
            return step
        if previous is not None and remaining is not None and remaining >= previous:
            step["result"] = "failed"
            step["error"] = f"no progress (remaining {remaining})"
            return step
        previous = remaining
    return {"name": job, "result": "failed", "exit": 1, "error": f"stopped after {limit} launches", "launches": limit}


def tiles_from(args, tiles_main, shots):
    argv = ["--out", args.tiles_out]
    if shots:
        argv += ["--shots", os.path.join(args.src, "satellite")]
        if args.png_dir:
            argv += ["--png-dir", args.png_dir]
    else:
        argv += ["--image", args.image, "--size", str(args.cfg["size"])]
    return call_main(tiles_main, argv)


def run_pipeline(args, launch=launch_process, buildings_main=buildings_to_json.main, roads_main=check_roads.main, tiles_main=make_tiles.main):
    steps = []
    state = {"result": "partial", "map": args.map_name, "src": args.src, "steps": steps}

    def publish():
        state["result"] = "partial" if not steps or steps[-1].get("result") == "done" else "failed"
        if steps and all(step.get("result") == "done" for step in steps) and state.get("finished"):
            state["result"] = "done"
        write_json(args.status_path, state)

    os.makedirs(args.src, exist_ok=True)
    publish()
    for job in args.jobs:
        if not args.skip_workbench:
            step = run_workbench_job(job, args.cfg, args.src, args.commands[job], launch)
            steps.append(step)
            publish()
            if step["result"] != "done":
                state["finished"] = True
                state["result"] = "failed"
                state["exit"] = step["exit"]
                publish()
                return step["exit"]
        if job == "buildings":
            code = call_main(buildings_main, ["--src", args.src, "--out", args.buildings_out, "--map", args.map_path])
            steps.append({"name": "buildings_json", "result": "done" if code == 0 else "failed", "exit": code, "out": args.buildings_out})
        elif job == "roads":
            code = call_main(roads_main, ["--src", args.src, "--min-dirt", str(args.min_dirt), "--min-bridge", str(args.min_bridge)])
            steps.append({"name": "check_roads", "result": "done" if code == 0 else "failed", "exit": code})
        elif job == "satellite" and not args.image:
            code = tiles_from(args, tiles_main, shots=True)
            steps.append({"name": "tiles", "result": "done" if code == 0 else "failed", "exit": code, "out": args.tiles_out})
        else:
            continue
        publish()
        if steps[-1]["result"] != "done":
            state["finished"] = True
            state["result"] = "failed"
            state["exit"] = steps[-1]["exit"]
            publish()
            return steps[-1]["exit"] or 1
    if args.image:
        code = tiles_from(args, tiles_main, shots=False)
        steps.append({"name": "tiles", "result": "done" if code == 0 else "failed", "exit": code, "out": args.tiles_out})
        publish()
        if steps[-1]["result"] != "done":
            state["finished"] = True
            state["result"] = "failed"
            state["exit"] = steps[-1]["exit"]
            publish()
            return steps[-1]["exit"] or 1
    state["finished"] = True
    state["result"] = "done"
    state["exit"] = 0
    publish()
    return 0


def build_args(argv):
    ap = argparse.ArgumentParser(description="Run the Workbench export and the Python steps with no clicks.")
    ap.add_argument("--map", default="everon", help="map name, or a path to a map json")
    ap.add_argument("--jobs", default="buildings,roads,satellite", help="comma list: buildings, roads, satellite")
    ap.add_argument("--max-tiles", type=int, default=2)
    ap.add_argument("--workbench", default="", help="ArmaReforgerWorkbenchSteam.exe")
    ap.add_argument("--profile", default="", help="Workbench profile folder")
    ap.add_argument("--src", default="", help="export folder (default: profile/reforger_map/<map>)")
    ap.add_argument("--image", default="", help="north-up island picture; skips assembling tiles from screenshots")
    ap.add_argument("--png-dir", default="", help="where Workbench wrote s_TX_TZ.png, if not beside the txt")
    ap.add_argument("--tiles-out", default="")
    ap.add_argument("--buildings-out", default="")
    ap.add_argument("--status", default="")
    ap.add_argument("--min-dirt", type=int, default=1)
    ap.add_argument("--min-bridge", type=int, default=1)
    ap.add_argument("--fov", default="")
    ap.add_argument("--height", default="")
    ap.add_argument("--skip-workbench", action="store_true", help="only run the Python steps on an export that is already done")
    ns = ap.parse_args(argv)
    resolved = resolve_map(ns.map)
    if not resolved:
        print("map json not found or has no world: " + ns.map, file=sys.stderr)
        raise SystemExit(2)
    map_path, map_name, cfg = resolved
    jobs = [part.strip() for part in ns.jobs.split(",") if part.strip()]
    if not jobs or any(job not in JOBS for job in jobs):
        print("jobs must be buildings, roads, satellite", file=sys.stderr)
        raise SystemExit(2)
    profile = ns.profile or default_profile()
    src = ns.src or export_dir(profile, map_name)
    exe = None
    commands = {}
    if not ns.skip_workbench:
        exe = find_workbench(ns.workbench)
        if not exe:
            print("ArmaReforgerWorkbenchSteam.exe not found. Pass --workbench.", file=sys.stderr)
            raise SystemExit(2)
        for job in jobs:
            commands[job] = workbench_command(exe, cfg, job, ns.max_tiles, map_name, ns.fov, ns.height)
    png_dir = ns.png_dir
    if not png_dir and not ns.image and "satellite" in jobs:
        screenshots = os.path.join(profile, "screenshots")
        if os.path.isdir(screenshots):
            png_dir = screenshots
    ns.map_path = map_path
    ns.map_name = map_name
    ns.cfg = cfg
    ns.jobs = jobs
    ns.src = src
    ns.workbench_exe = exe
    ns.commands = commands
    ns.png_dir = png_dir
    ns.tiles_out = ns.tiles_out or os.path.join(src, "tiles")
    ns.buildings_out = ns.buildings_out or os.path.join(src, "buildings.json")
    ns.status_path = ns.status or os.path.join(src, "pipeline.status.json")
    ns.min_dirt = ns.min_dirt
    ns.min_bridge = ns.min_bridge
    return ns


def main(argv=None):
    try:
        args = build_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        code = exc.code
        return 2 if code is None or not isinstance(code, int) else code
    return run_pipeline(args)


if __name__ == "__main__":
    sys.exit(main())
