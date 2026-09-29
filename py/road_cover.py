"""Which road pieces the export keeps.

MapExportPlugin uses these same role words. The old Everon road tool only walked
top-level entities. It wrote a line for a RoadEntity's SplinePoints, or for a
top-level shape whose direct child class contains RoadGenerator. It never read
the shape's own Points for a nested RoadEntity, and it never read
RoadNetworkBridgeComponent. The importer then ignored every line that was not
which=ctrl, so a dirt piece that only had a curve was dropped too. Bridge decks
were not RoadEntity, so they never got a line; the map guessed a straight join
from object boxes whose prefab contained /Bridges/.
"""

DIRT_MATERIAL = ("dirt", "forest", "gravel", "soil", "mud", "unpaved", "earth", "track")
DIRT_PREFAB = ("dirt", "forest", "gravel", "unpaved")
REAL_WHICH = ("curve", "spline", "points", "bridge")


def _has(text, word):
    return word in (text or "").lower()


def roadish(cls, prefab):
    return _has(cls, "road") or "/roads/" in (prefab or "").lower()


def role_of(cls, prefab, material, bridge_component=False):
    """bridge, dirt, path, road, or '' if this is not a road piece."""
    cls = cls or ""
    prefab = prefab or ""
    material = material or ""
    if _has(cls, "bridge") or _has(prefab, "bridge") or _has(material, "bridge"):
        role = "bridge"
    elif any(_has(material, word) for word in DIRT_MATERIAL) or (
        roadish(cls, prefab) and any(_has(prefab, word) for word in DIRT_PREFAB)
    ):
        role = "dirt"
    elif _has(material, "trail") or "/trail" in prefab.lower() or "/paths/" in prefab.lower():
        role = "path"
    elif roadish(cls, prefab):
        role = "road"
    else:
        role = ""
    if bridge_component and role != "dirt":
        return "bridge"
    return role


def old_has_line(cls, top_level, is_shape, generator_cls, point_sources):
    """True if the old Everon road tool would have written a line for this piece.

    point_sources uses the same words as the new export. The old tool only
    understood spline (RoadEntity SplinePoints) and curve (a top-level shape
    with a RoadGenerator child). Points on a RoadEntity, nested entities, and
    bridge components were ignored.
    """
    if not top_level:
        return False
    sources = set(point_sources)
    cls = cls or ""
    if "RoadEntity" in cls:
        if is_shape and "curve" in sources:
            return True
        return "spline" in sources
    if "ShapeEntity" in cls and generator_cls and "RoadGenerator" in generator_cls:
        return "curve" in sources or "spline" in sources
    return False


def new_has_line(cls, prefab, material, point_sources, has_bounds, parent_points=False, bridge_component=False, ancestor_exported=False):
    """True if this export writes a usable line.

    A nested RoadEntity whose spline lives on the parent shape uses that shape
    (parent_points). If the shape itself is exported, the child is not written
    again (ancestor_exported). Dirt must be a real line, not a bounds box.
    A bridge may use its component points or, if it has none, the long axis
    of its bounds.
    """
    if ancestor_exported and "RoadEntity" in (cls or ""):
        return False
    role = role_of(cls, prefab, material, bridge_component=bridge_component)
    if not role:
        return False
    sources = set(point_sources or [])
    if parent_points:
        sources.add("points")
    if bridge_component:
        sources.add("bridge")
    real = sources & set(REAL_WHICH)
    if role == "bridge":
        return bool(real) or has_bounds
    return bool(real)
