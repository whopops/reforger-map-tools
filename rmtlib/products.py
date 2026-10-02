"""What a user asks for ("roads", "line of sight", ...) turned into the export jobs and bake parts that make it.

`rmt.py run` and the GUI use this; `rmt.py export` and `bake` still take jobs and parts directly.

    plan(["roads", "los"], install=True)  ->  Plan(products, jobs, bakes, check, install, steps)

Dependencies are added on their own: trees need the line of sight (plants are placed on its ground), installing into
the field map needs everything it copies (rmt.py fieldmap refuses without roads, places, the line of sight and the
foliage measurements).
"""

from collections import namedtuple

# key: (title, what it gives, export jobs, bake parts, other products it needs, runs the real game)
PRODUCTS = {
    "roads": ("Roads", "The road and path network (roads.json)",
              ["probe", "mapdata", "roads"], ["roads"], [], False),
    "los": ("Terrain, objects and line of sight", "Ground heights, every object, roofs and canopy; the line-of-sight "
            "tiles and 10 m grids (los/, light/)",
            ["probe", "entities", "terrain", "surface"], ["los"], [], False),
    "places": ("Place names", "Towns, villages, hills and landmarks with their English names (places.json)",
               ["probe", "names"], ["places"], [], False),
    "satellite": ("Satellite imagery", "Top-down pictures of the whole map as web tiles (tiles/). Runs the game "
                  "on screen; a large map takes hours",
                  ["probe", "terrain", "satellite"], ["satellite"], [], True),
    "foliage": ("Trees and foliage", "Every tree and bush, and how see-through each kind is (foliage.json, plants/). "
                "Photographs each kind in the game on screen, about 100 s per kind",
                ["probe", "entities", "foliage"], ["foliage", "plants"], ["los"], True),
    "check": ("Accuracy check", "Fires engine sight lines and scores the line of sight against them",
              ["probe", "sightlines"], [], ["los"], False),
}
ORDER = ["roads", "los", "places", "satellite", "foliage", "check"]
INSTALL_NEEDS = ["roads", "los", "places", "foliage"]

JOB_ORDER = ["probe", "mapdata", "roads", "names", "entities", "terrain", "surface", "sightlines", "satellite",
             "foliage"]
BAKE_ORDER = ["roads", "los", "places", "satellite", "foliage", "plants"]

JOB_LABELS = {
    "probe": "Map size and chunk grid", "mapdata": "BI map data (roads, buildings, areas)", "roads": "Road pieces",
    "names": "Map names and labels", "entities": "Every object", "terrain": "Ground heights",
    "surface": "Roofs, canopy and cover", "sightlines": "Engine sight lines", "satellite": "Satellite pictures (game)",
    "foliage": "Plant photographs (game)",
}
BAKE_LABELS = {
    "roads": "Bake roads", "los": "Bake line of sight", "places": "Bake place names", "satellite": "Bake satellite tiles",
    "foliage": "Measure plant photographs", "plants": "Bake trees and bushes",
}
GAME_JOBS = {"satellite", "foliage"}

Plan = namedtuple("Plan", "products jobs bakes check install steps")


def closure(selected, install=False):
    """The products asked for plus the ones they need, in ORDER."""
    want = set(selected) | (set(INSTALL_NEEDS) if install else set())
    unknown = want - set(PRODUCTS)
    if unknown:
        raise SystemExit(f"unknown products: {', '.join(sorted(unknown))} (pick from {', '.join(ORDER)})")
    todo = list(want)
    while todo:
        for need in PRODUCTS[todo.pop()][4]:
            if need not in want:
                want.add(need)
                todo.append(need)
    return [p for p in ORDER if p in want]


def plan(selected, install=False):
    products = closure(selected, install)
    jobs = {j for p in products for j in PRODUCTS[p][2]}
    bakes = {b for p in products for b in PRODUCTS[p][3]}
    jobs = [j for j in JOB_ORDER if j in jobs]
    bakes = [b for b in BAKE_ORDER if b in bakes]
    check = "check" in products
    steps = [{"id": f"export:{j}", "label": JOB_LABELS.get(j, j), "game": j in GAME_JOBS} for j in jobs]
    steps += [{"id": f"bake:{b}", "label": BAKE_LABELS.get(b, b), "game": False} for b in bakes]
    if check:
        steps.append({"id": "check", "label": "Score the line of sight", "game": False})
    if install:
        steps.append({"id": "install", "label": "Install into the field map", "game": False})
    return Plan(products, jobs, bakes, check, install, steps)
