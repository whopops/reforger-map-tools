"""Every world on this PC, read straight from the addons' resource databases, without starting Workbench.

Each addon folder (the game's own under <game>\\addons, Workshop downloads under <Documents>\\My Games\\ArmaReforger\\
addons, your own Workbench projects) holds an addon.gproj (its GUID, title and the GUIDs it depends on) and a
resourceDatabase.rdb, which lists every file in the addon with its resource GUID: the bytes after a file's name are
its NUL, 6 bytes, then the GUID as 8 bytes little-endian (the layout blasttest.py's prefab_name reads, and the GUIDs
match the ones the engine reports: Arland {A9806AF617972E97}, Everon {853E92315D1D9EFE}).

A world's addon matters for the export: a mod map only loads when its addon, and every addon that one depends on, is
given to Workbench and the game. `world_addons` returns those GUIDs.
"""

import os
import re

GAME_GUID = "58D0FB3206B6F859"  # ArmaReforger.gproj, always loaded

_ENT = re.compile(rb"([A-Za-z0-9_\-./ ]+\.ent)\x00")


class Addon:
    def __init__(self, folder, source):
        self.folder = folder
        self.source = source          # "game", "workshop" or "project"
        self.id = os.path.basename(folder)
        self.guid = None
        self.title = self.id
        self.depends = []
        gproj = _find_gproj(folder)
        if gproj:
            with open(gproj, encoding="utf8", errors="replace") as f:
                text = f.read()
            m = re.search(r'\bGUID\s+"([0-9A-Fa-f]{16})"', text)
            self.guid = m.group(1).upper() if m else None
            m = re.search(r'\bTITLE\s+"([^"]*)"', text)
            if m and m.group(1).strip():
                self.title = m.group(1).strip()
            m = re.search(r"Dependencies\s*\{([^}]*)\}", text)
            if m:
                self.depends = [g.upper() for g in re.findall(r'"([0-9A-Fa-f]{16})"', m.group(1))]
        self.rdb = os.path.join(folder, "resourceDatabase.rdb")

    def worlds(self):
        """Every .ent in the addon as '{GUID}path'. From the rdb when there is one, else from the files on disk."""
        if os.path.isfile(self.rdb):
            with open(self.rdb, "rb") as f:
                data = f.read()
            out = []
            for m in _ENT.finditer(data):
                i = m.end()
                guid = data[i + 6:i + 14]
                if len(guid) == 8:
                    out.append("{%s}%s" % (guid[::-1].hex().upper(), m.group(1).decode("ascii", "replace")))
            return out
        out = []
        for root, _, files in os.walk(os.path.join(self.folder, "worlds")):
            for name in files:
                if name.lower().endswith(".ent"):
                    out.append(os.path.relpath(os.path.join(root, name), self.folder).replace("\\", "/"))
        return out


def _find_gproj(folder):
    for name in ("addon.gproj",):
        if os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    try:
        for name in os.listdir(folder):
            if name.lower().endswith(".gproj"):
                return os.path.join(folder, name)
    except OSError:
        pass
    return None


def installed(install):
    """Every addon this PC has, game first: [Addon]."""
    found = []
    roots = [(install.game_addons, "game"), (install.workshop_addons, "workshop"),
             (os.path.join(install.user_dir, "addons"), "project")]
    for root, source in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            folder = os.path.join(root, name)
            if os.path.isdir(folder) and _find_gproj(folder):
                found.append(Addon(folder, source))
    return found


def dependency_guids(guid, by_guid):
    """The addon and everything it needs, minus the game itself (always loaded)."""
    out, todo = [], [guid]
    while todo:
        g = todo.pop()
        if not g or g in out or g == GAME_GUID:
            continue
        a = by_guid.get(g)
        if a is not None and a.source == "game":
            continue
        out.append(g)
        if a is not None:
            todo.extend(a.depends)
    return out


# worlds that are not maps: tools, editor slots, menus, tests
_NOT_MAPS = re.compile(r"^worlds/(editor|mainmenuworld|test|tests|tutorial|sandbox)/|/test", re.I)


def is_terrain_world(resource):
    """True for the 'base' world of a terrain: worlds/<Name>/<Name>.ent or worlds/<Name>/Empty<Name>.ent (Eden,
    EmptyArland, ...). Game modes and scenarios (Conflict, Game Master, the campaign) sit deeper or under other names,
    on top of those terrains."""
    path = resource.split("}", 1)[-1]
    parts = path.split("/")
    if len(parts) != 3:
        return False
    stem = os.path.splitext(parts[-1])[0].lower()
    folder = parts[-2].lower()
    return stem == folder or stem == "empty" + folder


def list_worlds(install):
    """Every world: [{resource, name, addon, addonGuid, source, map, terrain}], game worlds first."""
    out = []
    for a in installed(install):
        for w in a.worlds():
            path = w.split("}", 1)[-1]
            if not path.lower().startswith("worlds/"):
                continue
            out.append({
                "resource": w,
                "name": os.path.splitext(os.path.basename(path))[0],
                "addon": a.title,
                "addonGuid": a.guid,
                "source": a.source,
                "map": not _NOT_MAPS.search(path),
                "terrain": is_terrain_world(w),
            })
    return out


def find_world(install, arg):
    """A world by resource ('{GUID}worlds/..', or 'worlds/..') or by file name: (resource, addon GUIDs to load, addon
    folders to add). None when nothing matches; SystemExit when a name matches several worlds."""
    addons = installed(install)
    by_guid = {a.guid: a for a in addons if a.guid}
    a = arg.replace("\\", "/").strip().lower()
    hits = []
    for addon in addons:
        for w in addon.worlds():
            low = w.lower()
            path = low.split("}", 1)[-1]
            stem = os.path.splitext(os.path.basename(path))[0]
            if a in (low, path) or (a == stem and path.startswith("worlds/")):
                hits.append((w, addon))
    exact = [h for h in hits if a in (h[0].lower(), h[0].lower().split("}", 1)[-1])]
    hits = exact or hits
    if not hits:
        return None
    if len({h[0] for h in hits}) > 1:
        raise SystemExit(f"'{arg}' matches several worlds:\n  " + "\n  ".join(sorted({h[0] for h in hits})))
    world, addon = hits[0]
    guids = [] if addon.source == "game" else dependency_guids(addon.guid, by_guid)
    # Workshop downloads are already in every launch's -addonsDir; a project of yours needs its parent folder added
    dirs = [os.path.dirname(addon.folder)] if addon.source == "project" else []
    return world, guids, dirs
