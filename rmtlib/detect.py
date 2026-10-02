"""What this PC has, as a list of checks for the GUI's Setup page (and `rmt.py detect`). Never raises: a missing
install is a failed check with a hint, not an exit.

Each check: {"key", "label", "state": "ok" | "warn" | "fail", "value", "hint"}.
"""

import importlib.util
import os
import shutil

from . import paths, steam


def _check(key, label, state, value="", hint=""):
    return {"key": key, "label": label, "state": state, "value": value, "hint": hint}


def _running():
    from .workbench import running
    try:
        return {"steam": bool(running("steam.exe")), "workbench": bool(running("ArmaReforgerWorkbench")),
                "game": bool(running("ArmaReforgerSteam"))}
    except OSError:
        return {}


def report(workbench_exe=None):
    out = []
    try:
        root = steam.steam_root()
        out.append(_check("steam", "Steam", "ok", root))
    except SystemExit as e:
        out.append(_check("steam", "Steam", "fail", str(e), "Install Steam and sign in."))
        return out

    game_dir, game_build = steam.app(steam.GAME_APP)
    out.append(_check("game", "Arma Reforger", "ok" if game_dir else "fail",
                      f"{game_dir}  (build {game_build})" if game_dir else "not installed",
                      "" if game_dir else "Install Arma Reforger from Steam (app 1874880)."))
    tools_dir, tools_build = steam.app(steam.TOOLS_APP)
    out.append(_check("tools", "Arma Reforger Tools", "ok" if tools_dir else "fail",
                      f"{tools_dir}  (build {tools_build})" if tools_dir else "not installed",
                      "" if tools_dir else "Install Arma Reforger Tools from Steam (in the Tools section, app 1874910)."))

    exe = workbench_exe or (os.path.join(tools_dir, "Workbench", steam.WORKBENCH_EXE) if tools_dir else None)
    if exe and os.path.isfile(exe):
        out.append(_check("workbench", "Workbench", "ok", exe))
    else:
        out.append(_check("workbench", "Workbench", "fail", exe or "not found",
                          "Point the app at ArmaReforgerWorkbenchSteamDiag.exe, or reinstall the Tools."))

    docs = steam._documents()
    out.append(_check("documents", "Documents folder", "ok", docs))
    wb_profile = os.path.join(docs, "My Games", "ArmaReforgerWorkbench", "profile")
    out.append(_check("wbprofile", "Workbench profile (raw export data goes here)",
                      "ok" if os.path.isdir(wb_profile) else "warn", wb_profile,
                      "" if os.path.isdir(wb_profile) else "Made the first time Workbench runs."))
    game_user = os.path.join(docs, "My Games", "ArmaReforger")
    workshop = os.path.join(game_user, "addons")
    mods = [d for d in os.listdir(workshop) if os.path.isdir(os.path.join(workshop, d))] if os.path.isdir(workshop) else []
    mods = [d for d in mods if os.path.isfile(os.path.join(workshop, d, "addon.gproj"))]
    out.append(_check("mods", "Workshop mods", "ok", f"{len(mods)} downloaded ({workshop})"))

    run = _running()
    if run:
        out.append(_check("steamrun", "Steam is running", "ok" if run["steam"] else "fail", "yes" if run["steam"] else "no",
                          "" if run["steam"] else "Start Steam: the game and Workbench need it."))
        out.append(_check("wbrun", "Workbench is closed", "fail" if run["workbench"] else "ok",
                          "open" if run["workbench"] else "closed",
                          "Close Workbench: an export needs it to itself." if run["workbench"] else ""))
        out.append(_check("gamerun", "The game is closed", "fail" if run["game"] else "ok",
                          "open" if run["game"] else "closed",
                          "Close Arma Reforger: satellite and foliage start it themselves." if run["game"] else ""))

    ws = paths.workspace()
    probe = ws
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        probe = parent if parent != probe else None
    if probe:
        free = shutil.disk_usage(probe).free / 1e9
        out.append(_check("disk", "Free space for the output", "ok" if free > 20 else "warn", f"{free:.0f} GB on {probe}",
                          "" if free > 20 else "A large map (Everon) needs tens of GB of raw data."))

    missing = [m for m in ("numpy", "PIL") if importlib.util.find_spec(m) is None]
    out.append(_check("python", "Python packages for baking", "fail" if missing else "ok",
                      "missing " + ", ".join(missing) if missing else "numpy, Pillow",
                      "pip install numpy pillow" if missing else ""))
    return out


def ready(checks):
    """True when nothing blocks a run."""
    return all(c["state"] != "fail" for c in checks)
