"""Place names and map icons for the site: places.json.

Source: the names job's descriptors.csv, i.e. every map descriptor placed in the world (what the in-game map labels
and icons come from), with their English names from the game's own string table (Language/localization.en_us.conf
in the game's paks). Only descriptors shown on the map, with a type set on the placed entity, are kept.

Output (site/places.json):
  {"version", "source",
   "towns":     [{"name", "type": City | Town | Village | Settlement, "xz": [x, z]}, ...],
   "landmarks": [{"name", "type": Area | Hill | Island | Water | Sea | Ridge | Valley, "xz": [x, z]}, ...],
   "pois":      [{"type": e.g. "Church", "Fuel station", "name"?, "xz": [x, z]}, ...]}
towns and landmarks match the field map's everon.json lists of the same name. The rest of everon.json (Conflict
bases, supplies, vehicles, caves) comes from game modes and outside guides, not from the world, and is not made here.
"""

import collections
import csv
import json
import os
import re
import time

from . import pak

# EMapDescriptorType (scripts/Game/generated/Map/EMapDescriptorType.c), in order from 0
MDT = ("TREE SMALLTREE BUSH BUILDING HOUSE FORESTERLODGE FORESTBORDER FORESTTRIANGLE FORESTSQUARE CALVARY CHURCH "
       "CHAPEL CROSS ROCK BUNKER FORTRESS FOUNTAIN SPRING VIEWPOINT TOWER VIEWTOWER WATERTOWER LIGHTHOUSE QUAY BUOY "
       "FUELSTATION HOSPITAL LIGHT FENCE WALL HIDE BUSSTOP BUSSTATION ROAD FOREST CRANE TRANSFORMER TRANSMITTER STACK "
       "RUIN TOURISM HILL TRACK MAINROAD ROCKS PLAYINGFIELD POWERLINES RAILWAY SHIPWRECK TOURISTSHELTER TOURISTSIGN "
       "MONUMENT WATERPUMP POLICE STORE HOTEL PUB FIREDEP NAME_GENERIC NAME_CITY NAME_VILLAGE NAME_TOWN "
       "NAME_SETTLEMENT NAME_HILL NAME_LOCAL NAME_ISLAND NAME_WATER_MINOR NAME_WATER_MAJOR NAME_SEA_MINOR "
       "NAME_SEA_MAJOR NAME_RIDGE NAME_VALLEY PARKING UNIT WILDLIFE CONSTRUCTION_SITE CURPOS WAYPOINT TARGET BASE PORT "
       "AIRPORT LANDMARK CAVE RADIO SPAWNPOINT TASK ICON").split()
TOWNS = {"NAME_CITY": "City", "NAME_TOWN": "Town", "NAME_VILLAGE": "Village", "NAME_SETTLEMENT": "Settlement"}
LANDMARKS = {"NAME_GENERIC": "Area", "NAME_LOCAL": "Area", "NAME_HILL": "Hill", "NAME_ISLAND": "Island",
             "NAME_WATER_MINOR": "Water", "NAME_WATER_MAJOR": "Water", "NAME_SEA_MINOR": "Sea",
             "NAME_SEA_MAJOR": "Sea", "NAME_RIDGE": "Ridge", "NAME_VALLEY": "Valley"}
SKIP = {"TREE", "SMALLTREE", "BUSH", "FORESTBORDER", "FORESTTRIANGLE", "FORESTSQUARE", "FOREST", "FENCE", "WALL",
        "ROAD", "MAINROAD", "TRACK", "POWERLINES", "RAILWAY", "LIGHT", "UNIT", "CURPOS", "WAYPOINT", "TARGET", "TASK",
        "ICON", "SPAWNPOINT", "BUILDING", "HOUSE"}


def strings():
    """English text for every string id in the game (the ids and texts are two parallel lists)."""
    text = pak.read_file("Language/localization.en_us.conf").decode("utf8", errors="replace")
    ids_part, _, texts_part = text.partition("\n Texts {")
    ids = re.findall(r'^\s*"(.*)"\s*$', ids_part, re.M)
    texts = [t.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
             for t in re.findall(r'^\s*"(.*)"\s*$', texts_part, re.M)]
    return dict(zip(ids, texts))


def label(mdt):
    return mdt.replace("FUELSTATION", "Fuel station").replace("VIEWTOWER", "View tower").replace(
        "WATERTOWER", "Water tower").replace("BUSSTOP", "Bus stop").replace("BUSSTATION", "Bus station").replace(
        "FIREDEP", "Fire station").replace("TOURISTSHELTER", "Tourist shelter").replace(
        "TOURISTSIGN", "Tourist sign").replace("PLAYINGFIELD", "Playing field").replace(
        "WATERPUMP", "Water pump").replace("FORESTERLODGE", "Forester lodge").replace(
        "CONSTRUCTION_SITE", "Construction site").capitalize()


def bake(raw, site, log=print):
    t0 = time.time()
    path = os.path.join(raw, "names", "descriptors.csv")
    if not os.path.isfile(path):
        log(f"places: no {path} (run the names job)")
        return None
    items = collections.defaultdict(dict)
    with open(path, encoding="utf8", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            key = (r["entity"], r["prefab"], r["name"], r["x"], r["z"], r["component"])
            items[key][r["var"]] = r["value"]
    tr = strings()
    towns, landmarks, pois = [], [], []
    for (_, prefab, ename, x, z, _), v in items.items():
        if v.get("VisibleOnMap", "") in ("0", "false") or v.get("Enabled", "") in ("0", "false"):
            continue
        t = v.get("MainType", "")
        if not t.strip().isdigit() or int(t) >= len(MDT):
            continue
        mdt = MDT[int(t)]
        name = v.get("DisplayName", "").strip()
        if name.startswith("#"):
            name = tr.get(name[1:], "")
        if name.isupper():  # hills, ridges, bays are written in capitals for the map's lettering
            name = " ".join(w.capitalize() for w in name.split())
        xz = [round(float(x), 1), round(float(z), 1)]
        if mdt in TOWNS and name:
            towns.append({"name": name, "type": TOWNS[mdt], "xz": xz})
        elif mdt in LANDMARKS and name:
            landmarks.append({"name": name, "type": LANDMARKS[mdt], "xz": xz})
        elif mdt not in SKIP and not mdt.startswith("NAME_"):
            p = {"type": label(mdt), "xz": xz}
            if name:
                p["name"] = name
            pois.append(p)
    towns.sort(key=lambda p: p["name"])
    landmarks.sort(key=lambda p: p["name"])
    pois.sort(key=lambda p: (p["type"], p["xz"]))
    doc = {"version": int(time.time()), "source": "the world's map descriptors, English names from the game",
           "towns": towns, "landmarks": landmarks, "pois": pois}
    os.makedirs(site, exist_ok=True)
    out = os.path.join(site, "places.json")
    with open(out, "w", encoding="utf8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    kinds = collections.Counter(p["type"] for p in pois)
    log(f"places: {len(towns)} towns, {len(landmarks)} landmarks, {len(pois)} icons "
        f"({', '.join(f'{k} {n}' for k, n in kinds.most_common(6))}); {os.path.getsize(out) / 1e3:.0f} kB "
        f"({time.time() - t0:.0f} s)")
    return doc
