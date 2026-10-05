"""The field map's reference layers for a map's Conflict scenario: static/data/<map>.json.

Source: the conflict job's conflict/entities.csv, run on the scenario world (worlds/MP/CTI_Campaign_<world>.ent), plus
the scenario's FIA cache spots (the SCR_CacheTerrainConfig its game mode names, from the game's paks) and English
names from the game's string table.

Output (the layout of the site's everon.json; the site reads every list, an empty one hides its layer):
  {"source",
   "conflict": [{"name", "kind": Main base (HQ) | Military base | Town base | Small base | Radio tower,
                 "control": true for a control point, "xz"}],
   "mob":      [{"name", "xz"}]                     where an HQ can start (bases that can be HQ)
   "supplies": [{"xz", "amount": "<n>" | "Infinite", "access": Vehicle | Foot}]
   "vehicles", "refuel", "repair": [{"xz"}]          vehicle spawns, fuel and repair stations
   "fia":      [{"name", "xz"}]                      every spot a FIA supply cache can appear
   "caves":    []                                    hand-made (Everon's come from Game Master guides), never exported
  }
A supply stash is a group of supply containers placed in the scenario (crates, cache compositions, depot buildings)
within 10 m of each other (a base's own supply pool is not one); its amount is what it holds at the start, "Infinite"
when it refills. Access is an estimate: Vehicle when a road (not a foot path) passes within 50 m (the map's
roads.json), else Foot. Checked on Everon against the older everon.json: the bases, HQ starts, vehicle spawns, refuel,
repair and FIA cache spots all match; supply stashes match in place and amount for most, access often differs.
"""

import collections
import csv
import json
import math
import os
import re

from . import pak
from .bake_places import strings

STASH_GAP = 10      # m: containers this close are one stash
ROAD_REACH = 50     # m: a stash this close to a road can be reached by vehicle


def read(raw):
    """{entity id: {"cls", "prefab", "name", "xz", "parent", "comps": {component: {var: value}}}}"""
    path = os.path.join(raw, "conflict", "entities.csv")
    if not os.path.isfile(path):
        raise SystemExit(f"no {path} (run the conflict job on the scenario world)")
    ents = {}
    with open(path, encoding="utf8", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            e = ents.setdefault(r["entity"], {"cls": r["class"], "prefab": r["prefab"], "name": r["name"],
                                              "xz": [round(float(r["x"]), 1), round(float(r["z"]), 1)],
                                              "parent": "", "comps": collections.defaultdict(dict)})
            if r["var"] == "_parent":
                e["parent"] = r["value"]
            elif r["var"] == "_component":
                e["comps"][r["component"]]
            else:
                e["comps"][r["component"]][r["var"]] = r["value"]
    return ents


def _text(tr, key):
    key = (key or "").strip()
    return tr.get(key[1:], "") if key.startswith("#") else key


def _words(s):
    """'MillPond' -> 'Mill Pond', 'StPierre Church' -> 'St Pierre Church'."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s).strip()


def _base_kind(e, b, town_names):
    n = e["name"]
    if b.get("m_eType") == "1" or "RelayRadio" in e["prefab"]:
        return "Radio tower"
    if re.match(r"(?i)(MainBase|HQ)", n):
        return "Main base (HQ)"
    if re.search(r"(?i)(Major|Military|Airport|Airfield|Airbase|Hospital|Harbou?r|Coastal)", n):
        return "Military base"
    if re.match(r"(?i)TownBase", n) or re.sub(r"(?i)base", "", n).lower() in town_names:
        return "Town base"
    return "Small base"


def bases(ents, tr, town_names):
    conflict, mob = [], []
    for e in ents.values():
        b = e["comps"].get("SCR_CampaignMilitaryBaseComponent")
        if b is None:
            continue
        name = _text(tr, b.get("m_sBaseName")) or _words(e["name"])
        if b.get("m_bCanBeHQ") == "1":
            num = re.search(r"(\d+)$", e["name"])
            mob.append({"name": f"HQ start {num.group(1)}" if num else "", "xz": e["xz"]})
            continue
        conflict.append({"name": name, "kind": _base_kind(e, b, town_names),
                         "control": b.get("m_bIsControlPoint") == "1", "xz": e["xz"]})
    # unnumbered ones (Arland's HQEast, HQWest) are numbered here, west to east
    taken = {m["name"] for m in mob}
    n = 0
    for m in sorted((m for m in mob if not m["name"]), key=lambda m: m["xz"]):
        n += 1
        while f"HQ start {n:02d}" in taken:
            n += 1
        m["name"] = f"HQ start {n:02d}"
    mob.sort(key=lambda m: m["name"])
    return conflict, mob


def _containers(e):
    """The supply containers an entity holds: [(start value, refills)]."""
    out = []
    for comp in ("SCR_ResourceComponent", "SCR_FactionBaseResourceComponent"):
        c = e["comps"].get(comp, {})
        for i in range(8):
            p = f"m_aContainers[{i}]."
            if p + "_class" not in c:
                break
            if c.get(p + "m_eStorageType") != "1" or c.get(p + "m_eResourceRights") != "4":
                continue
            cur = float(c.get(p + "m_fResourceValueCurrent") or 0)
            gain = c.get(p + "m_bEnableResourceGain") == "1"
            if cur > 0 or gain:
                out.append((cur, gain))
    return out


def _road_dist(xz, segs):
    best = 1e9
    x, z = xz
    for (ax, az), (bx, bz) in segs:
        dx, dz = bx - ax, bz - az
        t = 0 if dx == dz == 0 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz)))
        best = min(best, math.hypot(x - ax - t * dx, z - az - t * dz))
    return best


def supplies(ents, roads):
    pts = []
    for e in ents.values():
        if "SCR_CampaignMilitaryBaseComponent" in e["comps"] or "Vehicle" in e["cls"]:
            continue
        cs = _containers(e)
        if not cs:
            continue
        pts.append((e["xz"], sum(c for c, _ in cs), any(g for _, g in cs) or "_Campaign" in e["parent"]))
    # single-linkage groups
    group = list(range(len(pts)))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if math.dist(pts[i][0], pts[j][0]) <= STASH_GAP:
                group[root(i)] = root(j)
    stashes = collections.defaultdict(list)
    for i, p in enumerate(pts):
        stashes[root(i)].append(p)
    segs = []
    for a, b, kind, line, *_ in (roads or {}).get("edges", []):
        if kind < 3:
            segs.extend(zip(line, line[1:]))
    out = []
    for members in stashes.values():
        x = sum(p[0][0] for p in members) / len(members)
        z = sum(p[0][1] for p in members) / len(members)
        xz = [round(x, 1), round(z, 1)]
        infinite = any(p[2] for p in members)
        amount = "Infinite" if infinite else str(int(round(sum(p[1] for p in members))))
        access = "Vehicle" if segs and _road_dist(xz, segs) <= ROAD_REACH else "Foot"
        out.append({"xz": xz, "amount": amount, "access": access})
    out.sort(key=lambda s: s["xz"])
    return out


def points(ents, component):
    return sorted(({"xz": e["xz"]} for e in ents.values() if component in e["comps"]), key=lambda p: p["xz"])


def cache_spots(ents, world_stem):
    """The FIA cache spots: the cache pool config the game mode names, else CampaignCachePool_<world>.conf."""
    conf = ""
    for e in ents.values():
        conf = e["comps"].get("SCR_CacheManagerComponent", {}).get("m_sTerrainConfig", "") or conf
    path = re.sub(r"^\{[0-9A-F]+\}", "", conf) or f"Configs/Campaign/CampaignCachePool/CampaignCachePool_{world_stem}.conf"
    try:
        text = pak.read_file(path).decode("utf8", errors="replace")
    except FileNotFoundError:
        return []
    out = []
    for desc, x, _, z in re.findall(r'm_sDescription\s+"([^"]*)"\s+m_vPosition\s+(\S+)\s+(\S+)\s+(\S+)', text):
        out.append({"name": _words(desc), "xz": [round(float(x), 1), round(float(z), 1)]})
    return out


def bake(raw, world_stem, places=None, roads=None, log=print):
    ents = read(raw)
    tr = strings()
    towns = {re.sub(r"[^a-z]", "", t["name"].lower()) for t in (places or {}).get("towns", [])}
    conflict, mob = bases(ents, tr, towns)
    doc = {
        "source": {"pois": "game-extracted (reforger-map-tools conflict.py, the Conflict scenario)"},
        "conflict": conflict,
        "mob": mob,
        "supplies": supplies(ents, roads),
        "vehicles": points(ents, "SCR_AmbientVehicleSpawnPointComponent"),
        "refuel": points(ents, "SCR_FuelSupportStationComponent"),
        "repair": points(ents, "SCR_RepairSupportStationComponent"),
        "fia": cache_spots(ents, world_stem),
        "caves": [],
    }
    kinds = collections.Counter(c["kind"] for c in conflict)
    log(f"conflict: {len(conflict)} points ({', '.join(f'{k} {n}' for k, n in kinds.most_common())}), "
        f"{len(mob)} HQ starts, {len(doc['supplies'])} supply stashes "
        f"({sum(s['amount'] == 'Infinite' for s in doc['supplies'])} infinite), {len(doc['vehicles'])} vehicle spawns, "
        f"{len(doc['refuel'])} refuel, {len(doc['repair'])} repair, {len(doc['fia'])} FIA cache spots")
    return doc
