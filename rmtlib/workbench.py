"""Run one job in Workbench (or, for the satellite pictures, in the game itself) and watch it.

Workbench is started with its own folder as the working directory (otherwise "./addons" resolves wrongly and a
modal "Missing Addon" dialog blocks forever). Our scripts print "RMT|..." lines to the launch's console.log;
those are the heartbeat. No heartbeat for `stall` seconds means a dialog or a hang, and the process is killed.
Crash reporters that pop up during our run are closed.

The satellite capture runs in the real game (ArmaReforgerSteamDiag.exe) because command-line Workbench never
draws the world: every screenshot there came out black.
"""

import glob
import json
import os
import shutil
import subprocess
import time

from . import events, paths

GAME_GUID = "58D0FB3206B6F859"   # ArmaReforger.gproj
ADDON_GUID = "6A1F0C52D83E97B4"  # our addon
REPO = paths.REPO


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flashing up when the desktop app asks


class JobFailed(Exception):
    pass


def running(name_part):
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return [line.split(",")[1].strip('"') for line in out.splitlines() if name_part in line]


def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


def close_crash_reporters(since):
    """CrashReporter.exe waits for a click after a crash. Close only the ones that started during our run
    (since = time.time() at launch), never one the user already had open."""
    ps = ("Get-Process CrashReporter -ErrorAction SilentlyContinue | "
          "Where-Object { $_.StartTime -ge [DateTimeOffset]::FromUnixTimeSeconds(%d).LocalDateTime } | "
          "ForEach-Object { $_.Id }" % int(since))
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    pids = [p for p in out.split() if p.isdigit()]
    for pid in pids:
        kill_tree(pid)
    return len(pids)


def build_addon(extra_guids=()):
    """Our addon in <repo>/.build/ReforgerMapTools (see rmtlib/paths.py), depending on the game and on any mod
    addons a world needs. Built fresh each run so the committed addon never changes."""
    src = paths.addon_source()
    root = paths.build_root()
    dst = os.path.join(root, "ReforgerMapTools")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(src, "Scripts"), os.path.join(dst, "Scripts"))
    deps = "\n".join(f'  "{g}"' for g in [GAME_GUID, *extra_guids])
    with open(os.path.join(dst, "addon.gproj"), "w", encoding="utf8", newline="\n") as f:
        f.write('GameProject {\n ID "ReforgerMapTools"\n GUID "%s"\n TITLE "Reforger Map Tools - export"\n'
                ' Dependencies {\n%s\n }\n Configurations {\n  GameProjectConfig PC {\n  }\n }\n}\n' % (ADDON_GUID, deps))
    return root, os.path.join(dst, "addon.gproj")


def _backup_path(game_profile):
    return os.path.join(game_profile, "rmt", "video-settings-backup.json")


def _write_backup(game_profile, saved):
    path = _backup_path(game_profile)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8") as f:
        json.dump([{"path": p, "text": t} for p, t in saved], f)


def restore_video_settings(game_profile, log=print):
    """Put back the game's screen settings if a foliage run was killed before it could. Returns how many files."""
    path = _backup_path(game_profile)
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf8") as f:
        saved = json.load(f)
    for item in saved:
        with open(item["path"], "w", encoding="utf8", newline="") as f:
            f.write(item["text"])
    os.remove(path)
    log(f"restored the game's screen settings from an interrupted run ({len(saved)} file(s))")
    return len(saved)


def read_status(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf8") as f:
            return json.load(f)
    except ValueError:
        return None  # a half-written status is no status


def _has_content(path):
    if os.path.isfile(path):
        return os.path.getsize(path) > 0
    if os.path.isdir(path):
        return any(_has_content(os.path.join(path, name)) for name in os.listdir(path))
    return False


def succeeded(status, outputs=()):
    """The status contract every job's <job>.status.json follows (see docs/export-jobs.md, "Status"):
    done     the outputs exist, are not empty, and hold the rows the job claims
    partial  a declared incomplete output that is still usable, with an honest remaining count (> 0)
    failed   do not bake it, and do not skip the job next time
    So a missing status, failed, any other result, a partial that says nothing remains (that is done, or a bug), or a
    named output that is missing or empty is not success. outputs: files or folders (a folder must hold a non-empty
    file)."""
    if not status:
        return False
    result = status.get("result")
    if result == "partial":
        if not (status.get("remaining") or 0) > 0:
            return False
    elif result != "done":
        return False
    return all(_has_content(p) for p in outputs)


class Runner:
    """Launches one engine process (Workbench or the game) and supervises it through its console.log."""

    def __init__(self, install, addon_dirs=(), extra_guids=(), log=print):
        self.install = install
        self.log = log
        self.extra_guids = list(extra_guids)
        self.addon_root, self.gproj = build_addon(extra_guids)
        dirs = [self.addon_root, install.game_addons, os.path.join(install.workbench_dir, "addons"), *addon_dirs]
        if os.path.isdir(install.workshop_addons):
            dirs.append(install.workshop_addons)
        self.addon_dirs = ",".join(dirs)

    @staticmethod
    def _new_log(logs, before, started):
        for _ in range(240):
            now = set(glob.glob(os.path.join(logs, "logs_*")))
            fresh = [d for d in now - before if os.path.getmtime(d) >= started - 5]
            if fresh:
                return os.path.join(max(fresh, key=os.path.getmtime), "console.log")
            time.sleep(0.5)
        return None

    def _supervise(self, job, cmd, cwd, logs, status, stall, limit, finish_on_status, clear=()):
        for path in [status, *clear]:
            if os.path.exists(path):
                os.remove(path)
        before = set(glob.glob(os.path.join(logs, "logs_*")))
        started = time.time()
        proc = subprocess.Popen(cmd, cwd=cwd)
        lines = []
        try:
            console = self._new_log(logs, before, started)
            if not console:
                raise JobFailed("the process started but wrote no log")
            pos = 0
            last_beat = time.time()
            partial = b""
            while True:
                code = proc.poll()
                if os.path.isfile(console):
                    with open(console, "rb") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos += len(chunk)
                    *complete, partial = (partial + chunk).split(b"\n")
                    for raw in complete:
                        text = raw.decode("utf8", errors="replace").rstrip("\r")
                        if "RMT|" in text:
                            msg = text[text.index("RMT|") + 4:]
                            lines.append(msg)
                            last_beat = time.time()
                            events.heartbeat(job, msg)
                            # chunk lines: one in 25, and the last
                            if not msg.startswith("chunk|") or msg.endswith("|left=0") or len(lines) % 25 == 0:
                                self.log(f"  [{job}] {msg}")
                        elif "SCRIPT" in text and "(E)" in text:
                            self.log(f"  [{job}] {text.strip()}")
                            if "compile" in text.lower():
                                raise JobFailed(f"script error: {text.strip()}")
                if code is not None:
                    return code, lines, read_status(status)
                if finish_on_status and os.path.isfile(status):
                    time.sleep(3)
                    if proc.poll() is None:
                        kill_tree(proc.pid)
                        proc.wait(30)
                    return 0, lines, read_status(status)
                if time.time() - last_beat > stall:
                    raise JobFailed(f"no progress for {stall} s (a dialog, or a hang)")
                if time.time() - started > limit:
                    raise JobFailed(f"over the {limit} s limit")
                time.sleep(1)
        except BaseException:
            if proc.poll() is None:
                kill_tree(proc.pid)
                proc.wait(30)
            raise
        finally:
            if close_crash_reporters(started):
                self.log(f"  [{job}] closed a crash reporter")

    def status_path(self, out_rel, job, game=False):
        base = self.install.game_profile if game else self.install.profile
        return os.path.join(base, *out_rel.split("/"), f"{job}.status.json")

    def run(self, jobs, out_rel, world=None, args=(), stall=600, limit=24 * 3600):
        """Workbench plugin jobs, all on one load of the world. jobs is a name or a list, run in order.
        out_rel is the output folder under the Workbench profile. Every job's status file is removed first,
        so afterwards (even after a crash) status_path(out_rel, job) tells which jobs finished.
        Returns (exit code, RMT lines, status of the last job)."""
        if running("ArmaReforgerWorkbench"):
            raise JobFailed("Workbench is already running; close it first (rmt needs it to itself)")
        jobs = [jobs] if isinstance(jobs, str) else list(jobs)
        label = ",".join(jobs)
        statuses = [self.status_path(out_rel, j) for j in jobs]
        cmd = [self.install.exe, "-gproj", self.gproj, "-addonsDir", self.addon_dirs,
               "-wbModule=WorldEditor", "-plugin=RMT_ExportPlugin", f"-rmtJob={label}", f"-rmtOut=$profile:{out_rel}"]
        if world:
            cmd.append(f"-rmtWorld={world}")
        cmd += list(args)
        return self._supervise("workbench" if len(jobs) > 1 else jobs[0], cmd, self.install.workbench_dir,
                               self.install.logs, statuses[-1], stall, limit, False, clear=statuses[:-1])

    def _video_settings(self):
        return os.path.join(self.install.game_profile, ".save", "**", "settings", "ReforgerEngineSettings.conf")

    def run_game(self, job, out_rel, world, args=(), stall=600, limit=24 * 3600, flag="-rmtSat",
                 screen=None):
        """A capture in the game itself (it draws; command-line Workbench does not): the satellite pictures
        (flag -rmtSat) or the plant photographs (-rmtFoliage). out_rel is under the game's profile. The capture
        writes <job>.status.json and asks the game to close.
        screen = (width, height, mode) runs the game at that size (mode FULLSCREEN or BORDERLESS) by changing
        the video settings for the run only; the user's settings file is put back afterwards."""
        if running("ArmaReforgerSteam"):
            raise JobFailed("Arma Reforger is already running; close it first")
        status = self.status_path(out_rel, job, game=True)
        addons = ",".join([ADDON_GUID, *self.extra_guids])
        cmd = [self.install.game_exe, "-addonsDir", self.addon_dirs, "-addons", addons, "-world", world,
               flag, "1", f"-rmtOut=$profile:{out_rel}"]
        cmd += ["-nosplash"] if screen else ["-window", "-nosplash"]
        cmd += list(args)
        # a run killed half way (the GUI's Cancel kills the whole process tree) left the screen settings changed
        restore_video_settings(self.install.game_profile, self.log)
        saved = []
        if screen:
            import re
            width, height, mode = screen
            for path in glob.glob(self._video_settings(), recursive=True):
                with open(path, encoding="utf8", newline="") as f:
                    original = f.read()
                text = original
                for key, value in (("WindowMode", mode), ("ScreenWidth", width), ("ScreenHeight", height),
                                   ("WindowPosX", 0), ("WindowPosY", 0)):
                    text = re.sub(r"(?m)^(\s*%s )\S+" % key, lambda m: f"{m.group(1)}{value}", text)
                saved.append((path, original))
                _write_backup(self.install.game_profile, saved)
                with open(path, "w", encoding="utf8", newline="") as f:
                    f.write(text)
        try:
            return self._supervise(job, cmd, self.install.game_dir, self.install.game_logs, status, stall, limit,
                                   finish_on_status=True)
        finally:
            for path, original in saved:
                with open(path, "w", encoding="utf8", newline="") as f:
                    f.write(original)
            if saved:
                os.remove(_backup_path(self.install.game_profile))


Workbench = Runner  # older name
