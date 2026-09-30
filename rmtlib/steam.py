"""Where Steam, Arma Reforger and Arma Reforger Tools are installed, and which builds they are."""

import os
import re
import winreg

GAME_APP = "1874880"
TOOLS_APP = "1874910"
WORKBENCH_EXE = "ArmaReforgerWorkbenchSteamDiag.exe"


def steam_root():
    for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
        try:
            with winreg.OpenKey(hive, key) as k:
                for name in ("SteamPath", "InstallPath"):
                    try:
                        path = winreg.QueryValueEx(k, name)[0]
                        if path and os.path.isdir(path):
                            return os.path.normpath(path)
                    except OSError:
                        pass
        except OSError:
            pass
    raise SystemExit("Steam is not installed (no Steam path in the registry)")


def libraries():
    root = steam_root()
    libs = [root]
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        with open(vdf, encoding="utf8", errors="replace") as f:
            for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                p = os.path.normpath(m.group(1).replace("\\\\", "\\"))
                if p not in libs:
                    libs.append(p)
    return libs


def app(appid):
    """(install folder, build id) of an installed Steam app."""
    for lib in libraries():
        acf = os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf")
        if not os.path.isfile(acf):
            continue
        with open(acf, encoding="utf8", errors="replace") as f:
            text = f.read()
        folder = re.search(r'"installdir"\s+"([^"]+)"', text)
        build = re.search(r'"buildid"\s+"(\d+)"', text)
        path = os.path.join(lib, "steamapps", "common", folder.group(1)) if folder else None
        if path and os.path.isdir(path):
            return path, build.group(1) if build else "unknown"
    return None, None


class Install:
    """Everything rmt needs to know about this PC's Reforger install."""

    def __init__(self, workbench_exe=None):
        self.game_dir, self.game_build = app(GAME_APP)
        self.tools_dir, self.tools_build = app(TOOLS_APP)
        if not self.game_dir:
            raise SystemExit("Arma Reforger is not installed (Steam app 1874880)")
        if workbench_exe:
            self.exe = workbench_exe
        else:
            if not self.tools_dir:
                raise SystemExit("Arma Reforger Tools is not installed (Steam app 1874910)")
            self.exe = os.path.join(self.tools_dir, "Workbench", WORKBENCH_EXE)
        if not os.path.isfile(self.exe):
            raise SystemExit(f"Workbench not found at {self.exe}")
        self.workbench_dir = os.path.dirname(self.exe)
        self.game_addons = os.path.join(self.game_dir, "addons")
        docs = _documents()
        self.user_dir = os.path.join(docs, "My Games", "ArmaReforgerWorkbench")
        self.profile = os.path.join(self.user_dir, "profile")
        self.logs = os.path.join(self.user_dir, "logs")
        # The game itself (the satellite pictures are taken there) and its own profile and logs
        self.game_exe = os.path.join(self.game_dir, "ArmaReforgerSteamDiag.exe")
        self.game_user = os.path.join(docs, "My Games", "ArmaReforger")
        self.game_profile = os.path.join(self.game_user, "profile")
        self.game_logs = os.path.join(self.game_user, "logs")
        # Workshop addons the game has downloaded (mod maps live here)
        self.workshop_addons = os.path.join(self.game_user, "addons")


def _documents():
    """The real Documents folder (it may be redirected, e.g. to OneDrive)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            path = os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0])
            if os.path.isdir(path):
                return path
    except OSError:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")
