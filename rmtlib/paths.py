"""Where rmt keeps its files: the workspace (manifests, site data, the world list), the addon it builds for each run,
and the addon's source.

From the repo nothing changes: the workspace is <repo>/out and the addon is built in <repo>/.build. The GUI (or
`rmt.py --workspace <folder>`, or the RMT_WORKSPACE environment variable) points the workspace at a folder the user
chose. In the packaged app the addon's source comes from the bundle and is built under %LOCALAPPDATA%, because the
install folder may be read-only.

Raw export data is not here: scripts may only write under the engine's own profile ($profile:), so raw output stays
in <Documents>\\My Games\\ArmaReforgerWorkbench\\profile\\rmt (and the game's profile for the game-side jobs). The
manifest of each run records where.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = bool(getattr(sys, "frozen", False))

_workspace = os.environ.get("RMT_WORKSPACE") or None


def bundle():
    """The folder holding addon/ (the repo, or the unpacked app bundle)."""
    return getattr(sys, "_MEIPASS", REPO) if FROZEN else REPO


def app_data():
    """Per-user folder for things the app makes and keeps (the built addon, settings)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ReforgerMapTools")


def workspace():
    """Manifests, site data and the world list go here: <workspace>/<slug>/<build>/."""
    if _workspace:
        return _workspace
    if FROZEN:
        return os.path.join(os.path.expanduser("~"), "Documents", "ReforgerMapTools")
    return os.path.join(REPO, "out")


def set_workspace(path):
    global _workspace
    _workspace = os.path.abspath(path) if path else None


def addon_source():
    return os.path.join(bundle(), "addon")


def build_root():
    """Where the addon is built fresh for every launch (Workbench is given this folder in -addonsDir)."""
    return os.path.join(app_data(), "build") if FROZEN else os.path.join(REPO, ".build")
